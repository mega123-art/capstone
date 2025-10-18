"""
Claim Winnings Script - Collect payouts from resolved markets
Only winners can claim their share of the pot
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import Optional

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

# Seeds
MARKET_SEED = b"market"
VAULT_SEED = b"vault"
POSITION_SEED = b"position"

# Instruction discriminator for claim_winnings
CLAIM_WINNINGS_DISCRIMINATOR = bytes([161, 215, 24, 59, 14, 236, 242, 221])


class WinningsClaimer:
    def __init__(self, user_keypair_path: str):
        """Initialize winnings claimer"""
        keypair_path = Path(user_keypair_path).expanduser()
        with open(keypair_path, 'r') as f:
            secret_key = json.load(f)
        self.user_keypair = Keypair.from_bytes(bytes(secret_key))
        self.client = AsyncClient(SOLANA_RPC_URL, commitment=Confirmed)
    
    def find_pda(self, seeds: list) -> tuple:
        """Find PDA"""
        pda, bump = Pubkey.find_program_address(seeds, PROGRAM_ID)
        return pda, bump
    
    def encode_u64(self, value: int) -> bytes:
        """Encode u64"""
        return value.to_bytes(8, 'little')
    
    async def get_market_info(self, market_id: int) -> Optional[dict]:
        """Fetch market information"""
        try:
            market_pda, _ = self.find_pda([MARKET_SEED, self.encode_u64(market_id)])
            account_info = await self.client.get_account_info(market_pda)
            
            if account_info.value is None:
                return None
            
            data = account_info.value.data
            
            # Parse market data
            offset = 16  # Skip discriminator + market_id
            offset += 32  # Skip authority
            
            # Skip strings
            for _ in range(3):
                str_len = int.from_bytes(data[offset:offset+4], 'little')
                offset += 4 + str_len
            
            # Skip times and liquidity
            offset += 16 + 8*5
            
            # Read resolved and outcome
            resolved = data[offset] == 1
            offset += 1
            
            # Read outcome (Option<bool>)
            has_outcome = data[offset] == 1
            offset += 1
            outcome = None
            if has_outcome:
                outcome = data[offset] == 1
            
            return {
                'market_pda': market_pda,
                'resolved': resolved,
                'outcome': outcome
            }
            
        except Exception as e:
            print(f"Error fetching market: {e}")
            return None
    
    async def get_position_info(self, market_id: int) -> Optional[dict]:
        """Fetch user position"""
        try:
            position_pda, _ = self.find_pda([
                POSITION_SEED,
                bytes(self.user_keypair.pubkey()),
                self.encode_u64(market_id)
            ])
            
            account_info = await self.client.get_account_info(position_pda)
            
            if account_info.value is None:
                return None
            
            data = account_info.value.data
            
            # Parse position data
            # Skip discriminator (8 bytes) + user pubkey (32 bytes) + market_id (8 bytes)
            offset = 48
            
            yes_shares = int.from_bytes(data[offset:offset+8], 'little')
            offset += 8
            no_shares = int.from_bytes(data[offset:offset+8], 'little')
            offset += 8
            claimed = data[offset] == 1
            
            return {
                'position_pda': position_pda,
                'yes_shares': yes_shares,
                'no_shares': no_shares,
                'claimed': claimed
            }
            
        except Exception as e:
            print(f"Error fetching position: {e}")
            return None
    
    async def claim_winnings(self, market_id: int) -> bool:
        """Claim winnings from a resolved market"""
        
        print(f"\n{'='*60}")
        print(f"💰 CLAIMING WINNINGS")
        print(f"{'='*60}")
        print(f"Market ID: {market_id}")
        print(f"User: {self.user_keypair.pubkey()}\n")
        
        # Get market info
        print("📊 Checking market status...")
        market_info = await self.get_market_info(market_id)
        
        if not market_info:
            print("❌ Market not found!\n")
            return False
        
        if not market_info['resolved']:
            print("❌ Market not resolved yet! Cannot claim.\n")
            return False
        
        if market_info['outcome'] is None:
            print("❌ Market outcome not set!\n")
            return False
        
        outcome_str = "YES" if market_info['outcome'] else "NO"
        print(f"   Market resolved: {outcome_str}\n")
        
        # Get position info
        print("📈 Checking your position...")
        position_info = await self.get_position_info(market_id)
        
        if not position_info:
            print("❌ No position found! You didn't trade in this market.\n")
            return False
        
        if position_info['claimed']:
            print("❌ Already claimed! You've already collected your winnings.\n")
            return False
        
        print(f"   YES shares: {position_info['yes_shares'] / 1e9:.6f}")
        print(f"   NO shares: {position_info['no_shares'] / 1e9:.6f}\n")
        
        # Check if user has winning shares
        if market_info['outcome']:  # YES won
            winning_shares = position_info['yes_shares']
        else:  # NO won
            winning_shares = position_info['no_shares']
        
        if winning_shares == 0:
            print(f"❌ You don't have any winning shares!")
            print(f"   Market resolved as {outcome_str}, but you bet on the opposite.\n")
            return False
        
        print(f"✅ You have {winning_shares / 1e9:.6f} winning shares!")
        print(f"   Claiming your payout...\n")
        
        # Build transaction
        print("🔨 Building transaction...")
        
        try:
            market_pda, _ = self.find_pda([MARKET_SEED, self.encode_u64(market_id)])
            vault_pda, _ = self.find_pda([VAULT_SEED, self.encode_u64(market_id)])
            position_pda = position_info['position_pda']
            
            # Build instruction (no data needed for claim_winnings)
            instruction = Instruction(
                program_id=PROGRAM_ID,
                accounts=[
                    AccountMeta(pubkey=market_pda, is_signer=False, is_writable=False),
                    AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=position_pda, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=self.user_keypair.pubkey(), is_signer=True, is_writable=True),
                    AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
                ],
                data=CLAIM_WINNINGS_DISCRIMINATOR
            )
            
            # Send transaction
            print("📤 Sending transaction...")
            
            blockhash_resp = await self.client.get_latest_blockhash()
            recent_blockhash = blockhash_resp.value.blockhash
            
            message = Message.new_with_blockhash(
                [instruction],
                self.user_keypair.pubkey(),
                recent_blockhash
            )
            
            transaction = Transaction([self.user_keypair], message, recent_blockhash)
            
            tx_opts = TxOpts(skip_preflight=False, preflight_commitment=Confirmed)
            response = await self.client.send_transaction(transaction, opts=tx_opts)
            
            signature = response.value
            print(f"   Transaction: {signature}")
            
            # Confirm
            print("⏳ Confirming...")
            await self.client.confirm_transaction(signature, commitment=Confirmed)
            
            print(f"\n🎉 SUCCESS! WINNINGS CLAIMED!")
            print(f"   Check your wallet - you've been paid!")
            print(f"   Transaction: {signature}")
            print(f"   Explorer: https://explorer.solana.com/tx/{signature}?cluster=devnet\n")
            print(f"{'='*60}\n")
            
            return True
            
        except Exception as e:
            print(f"\n❌ Transaction failed: {e}\n")
            print(f"{'='*60}\n")
            return False
    
    async def close(self):
        """Close connection"""
        await self.client.close()


async def main():
    """Main entry point"""
    
    # Parse arguments
    if len(sys.argv) < 2:
        print("\n" + "="*60)
        print("💰 CLAIM WINNINGS - Collect Your Payouts")
        print("="*60)
        print("\nUsage: python claim_winnings.py <market_id>")
        print("\nExamples:")
        print("  python claim_winnings.py 0")
        print("  python claim_winnings.py 1")
        print("  python claim_winnings.py 2")
        print("\nArguments:")
        print("  market_id : Market number to claim from (0, 1, 2, ...)")
        print("\nNote:")
        print("  - Market must be resolved")
        print("  - You must have winning shares")
        print("  - Can only claim once per market")
        print("\n" + "="*60 + "\n")
        sys.exit(1)
    
    # Parse market_id
    try:
        market_id = int(sys.argv[1])
    except ValueError:
        print("❌ Invalid market_id! Must be a number.")
        sys.exit(1)
    
    # Get user keypair
    user_keypair_path = os.getenv("USER_KEYPAIR", "~/.config/solana/id.json")
    
    # Create claimer and execute
    claimer = WinningsClaimer(user_keypair_path)
    
    try:
        success = await claimer.claim_winnings(market_id)
        sys.exit(0 if success else 1)
    finally:
        await claimer.close()


if __name__ == "__main__":
    asyncio.run(main())