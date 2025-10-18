"""
Buy Shares Script - Trade in Prediction Markets
Supports both YES and NO shares with AMM pricing

USAGE: python buy_shares.py <market_id> <yes|no> <amount_sol>

Keypair paths are loaded from environment variables (USER_KEYPAIR and AUTHORITY_KEYPAIR)
or default to ~/.config/solana/id.json.
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import Optional, List

# Solana imports
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solders.transaction import Transaction
from solders.message import Message
from solders.instruction import Instruction, AccountMeta
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts

# Load environment
from dotenv import load_dotenv
load_dotenv()

# Configuration
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
PROGRAM_ID = Pubkey.from_string(os.getenv("PROGRAM_ID", "EynCGpDcqKdBZq5YXbtZuFnxXEHzkqDYkXNmstHiDc2C"))
DEFAULT_SLIPPAGE = float(os.getenv("SLIPPAGE_TOLERANCE", "0.05"))  # 5% default slippage
TRADE_TO_POOL_LIMIT = 25  # reject trades > 25x pool liquidity

# Seeds
MARKET_SEED = b"market"
VAULT_SEED = b"vault"
CONFIG_SEED = b"config"
POSITION_SEED = b"position"

# Instruction discriminator for buy_shares
BUY_SHARES_DISCRIMINATOR = bytes([40, 239, 138, 154, 8, 37, 106, 108])


class ShareBuyer:
    def __init__(self, user_keypair_path: str):
        """Initialize share buyer, loading user and authority keypairs safely."""
        
        # --- Load User Keypair ---
        user_keypair_source = user_keypair_path
        user_secret = None
        try:
            user_secret = json.loads(user_keypair_source)
        except json.JSONDecodeError:
            try:
                user_path = Path(user_keypair_source).expanduser()
                with open(user_path, 'r') as f:
                    user_secret = json.load(f)
            except Exception as file_error:
                print(f"FATAL ERROR: Could not load User Keypair from '{user_keypair_source}'. {file_error}")
                sys.exit(1)
        try:
            self.user_keypair = Keypair.from_bytes(bytes(user_secret))
        except Exception as key_error:
            print(f"FATAL ERROR: Invalid User Keypair. {key_error}")
            sys.exit(1)

        # --- Load Authority Keypair ---
        authority_keypair_source = os.getenv("AUTHORITY_KEYPAIR", "~/.config/solana/id.json")
        auth_secret = None
        try:
            auth_secret = json.loads(authority_keypair_source)
        except json.JSONDecodeError:
            try:
                authority_path = Path(authority_keypair_source).expanduser()
                with open(authority_path, 'r') as f:
                    auth_secret = json.load(f)
            except Exception as file_error:
                print(f"FATAL ERROR: Could not load Authority Keypair from '{authority_keypair_source}'. {file_error}")
                sys.exit(1)
        try:
            self.authority_pubkey = Keypair.from_bytes(bytes(auth_secret)).pubkey()
        except Exception as key_error:
            print(f"FATAL ERROR: Invalid Authority Keypair. {key_error}")
            sys.exit(1)

        self.client = AsyncClient(SOLANA_RPC_URL, commitment=Confirmed)
        print(f"User Pubkey: {self.user_keypair.pubkey()}")
        print(f"Authority Pubkey (Fee Recipient): {self.authority_pubkey}")

    def find_pda(self, seeds: List[bytes]) -> tuple:
        pda, bump = Pubkey.find_program_address(seeds, PROGRAM_ID)
        return pda, bump

    def encode_u64(self, value: int) -> bytes:
        return value.to_bytes(8, 'little')

    def encode_bool(self, value: bool) -> bytes:
        return bytes([1 if value else 0])

    async def get_market_info(self, market_id: int) -> Optional[dict]:
        """Fetch simplified market info"""
        try:
            market_pda, _ = self.find_pda([MARKET_SEED, self.encode_u64(market_id)])
            account_info = await self.client.get_account_info(market_pda)
            if account_info.value is None:
                return None
            data = account_info.value.data
            offset = 16 + 32  # discriminator + authority
            for _ in range(3):
                str_len = int.from_bytes(data[offset:offset+4], 'little')
                offset += 4 + str_len
            offset += 16  # timestamps
            if len(data) < offset + 5*8 + 1:
                raise ValueError("Market data too short.")
            initial_liquidity = int.from_bytes(data[offset:offset+8], 'little'); offset += 8
            yes_liquidity = int.from_bytes(data[offset:offset+8], 'little'); offset += 8
            no_liquidity = int.from_bytes(data[offset:offset+8], 'little'); offset += 8
            k_constant = int.from_bytes(data[offset:offset+8], 'little'); offset += 8
            total_volume = int.from_bytes(data[offset:offset+8], 'little'); offset += 8
            resolved = data[offset] == 1
            return {
                'market_pda': market_pda,
                'yes_liquidity': yes_liquidity,
                'no_liquidity': no_liquidity,
                'k_constant': k_constant,
                'total_volume': total_volume,
                'resolved': resolved
            }
        except Exception as e:
            print(f"Error fetching market {market_id}: {e}")
            return None

    def calculate_price(self, is_yes: bool, yes_liquidity: int, no_liquidity: int) -> float:
        total = yes_liquidity + no_liquidity
        if total == 0:
            return 0.5
        return (no_liquidity / total) if is_yes else (yes_liquidity / total)

    async def buy_shares(self, market_id: int, is_yes: bool, amount_sol: float,
                         min_shares: Optional[int] = None) -> bool:
        print(f"\n{'='*60}")
        print(f"💰 BUYING {'YES' if is_yes else 'NO'} SHARES")
        print(f"{'='*60}")
        print(f"Market ID: {market_id}")
        print(f"Amount: {amount_sol} SOL")
        print(f"User: {self.user_keypair.pubkey()}\n")

        print("📊 Fetching market data...")
        market_info = await self.get_market_info(market_id)
        if not market_info or market_info['resolved']:
            print("❌ Market unavailable or resolved.")
            return False

        yes_liq = market_info['yes_liquidity']
        no_liq = market_info['no_liquidity']
        total_liq = yes_liq + no_liq
        current_price = self.calculate_price(is_yes, yes_liq, no_liq)

        print(f"  YES liquidity: {yes_liq/1e9:.4f} SOL")
        print(f"  NO liquidity:  {no_liq/1e9:.4f} SOL")
        print(f"  Current {'YES' if is_yes else 'NO'} price: {current_price:.4f} SOL\n")

        amount_lamports = int(amount_sol * 1e9)

        if total_liq == 0:
            print("❌ Market has zero liquidity.")
            return False
        if amount_lamports > total_liq * TRADE_TO_POOL_LIMIT:
            print(f"❌ Trade too large ({amount_sol:.3f} SOL) vs pool ({total_liq/1e9:.6f} SOL).")
            return False

                # Estimate shares and min_shares correctly (no atomic scaling)
        estimated_shares = amount_sol / current_price
        slippage = DEFAULT_SLIPPAGE
        min_shares = estimated_shares * (1.0 - slippage)
        if min_shares < 0:
            min_shares = 0

        print(f"📈 Estimated shares: {estimated_shares:.6f}")
        print(f"📈 Slippage: {slippage*100:.2f}% → min_shares = {min_shares:.6f}\n")


        try:
            market_pda, _ = self.find_pda([MARKET_SEED, self.encode_u64(market_id)])
            vault_pda, _ = self.find_pda([VAULT_SEED, self.encode_u64(market_id)])
            config_pda, _ = self.find_pda([CONFIG_SEED])
            position_pda, _ = self.find_pda([
                POSITION_SEED,
                bytes(self.user_keypair.pubkey()),
                self.encode_u64(market_id)
            ])

            data = (
                BUY_SHARES_DISCRIMINATOR +
                self.encode_bool(is_yes) +
                self.encode_u64(amount_lamports) +
                self.encode_u64(int(min_shares))
            )

            instruction = Instruction(
                program_id=PROGRAM_ID,
                accounts=[
                    AccountMeta(config_pda, False, False),
                    AccountMeta(market_pda, False, True),
                    AccountMeta(vault_pda, False, True),
                    AccountMeta(position_pda, False, True),
                    AccountMeta(self.user_keypair.pubkey(), True, True),
                    AccountMeta(self.authority_pubkey, False, True),
                    AccountMeta(SYS_PROGRAM_ID, False, False)
                ],
                data=data
            )

            print("📤 Sending transaction...")
            blockhash_resp = await self.client.get_latest_blockhash()
            recent_blockhash = blockhash_resp.value.blockhash
            message = Message.new_with_blockhash(
                [instruction], self.user_keypair.pubkey(), recent_blockhash
            )
            transaction = Transaction([self.user_keypair], message, recent_blockhash)
            tx_opts = TxOpts(skip_preflight=False, preflight_commitment=Confirmed)
            response = await self.client.send_transaction(transaction, opts=tx_opts)
            signature = response.value

            print(f"  Transaction: {signature}")
            print("⏳ Confirming...")
            await self.client.confirm_transaction(signature, commitment=Confirmed)

            print(f"\n✅ SUCCESS! Bought {'YES' if is_yes else 'NO'} shares.")
            print(f"🔗 Explorer: https://explorer.solana.com/tx/{signature}?cluster=devnet\n")
            print(f"{'='*60}\n")
            return True

        except Exception as e:
            err = str(e)
            if 'Instruction: Custom' in err or 'Program log' in err:
                print("\n❌ Smart Contract Error Detected:")
                parts = err.split('Program log:')
                if len(parts) > 1:
                    print(f"   {parts[-1].strip()}")
                else:
                    print(f"   {err}")
                print(f" (Program ID: {PROGRAM_ID})\n")
            else:
                print(f"\n❌ Transaction failed: {err}\n")
            print(f"{'='*60}\n")
            return False

    async def close(self):
        await self.client.close()


async def main():
    if len(sys.argv) < 4:
        print("\nUsage: python buy_shares.py <market_id> <yes|no> <amount_sol>")
        print("Example: python buy_shares.py 0 yes 0.01\n")
        sys.exit(1)

    try:
        market_id = int(sys.argv[1])
        side = sys.argv[2].lower()
        amount_sol = float(sys.argv[3])
        if side not in ['yes', 'no']:
            print("❌ Side must be 'yes' or 'no'")
            sys.exit(1)
        if amount_sol <= 0:
            print("❌ Amount must be positive")
            sys.exit(1)
        is_yes = (side == 'yes')
    except ValueError as e:
        print(f"❌ Invalid arguments: {e}")
        sys.exit(1)

    user_keypair_path = os.getenv("USER_KEYPAIR", "~/.config/solana/id.json")
    buyer = ShareBuyer(user_keypair_path)

    try:
        success = await buyer.buy_shares(market_id, is_yes, amount_sol)
        sys.exit(0 if success else 1)
    finally:
        await buyer.close()


if __name__ == "__main__":
    print("""\n
╔══════════════════════════════════════════╗
║     🚀 Solana Prediction Market Buyer    ║
╚══════════════════════════════════════════╝
""")
    try:
        asyncio.run(main())
    except SystemExit:
        pass
    except KeyboardInterrupt:
        print("\n👋 Script stopped by user.")
    except Exception as e:
        print(f"\nCritical script failure: {e}")
