"""
Manual Prediction Market Bot - No AI Required!
You create markets and resolve them manually
"""

import os
import json
import time
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from pathlib import Path

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

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Configuration
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
PROGRAM_ID = Pubkey.from_string(os.getenv("PROGRAM_ID", "EynCGpDcqKdBZq5YXbtZuFnxXEHzkqDYkXNmstHiDc2C"))

# Seeds for PDAs
MARKET_SEED = b"market"
VAULT_SEED = b"vault"
USER_POSITION_SEED = b"position"
CONFIG_SEED = b"config"

# Instruction discriminators (from IDL)
INITIALIZE_DISCRIMINATOR = bytes([175, 175, 109, 31, 13, 152, 155, 237])
CREATE_MARKET_DISCRIMINATOR = bytes([103, 226, 97, 235, 200, 188, 251, 254])
RESOLVE_MARKET_DISCRIMINATOR = bytes([155, 23, 80, 173, 46, 74, 23, 239])


class ManualPredictionMarketBot:
    def __init__(self, authority_keypair_path: str):
        """Initialize the manual bot with authority keypair"""
        # Load authority keypair
        keypair_path = Path(authority_keypair_path).expanduser()
        with open(keypair_path, 'r') as f:
            secret_key = json.load(f)
        self.authority_keypair = Keypair.from_bytes(bytes(secret_key))
        
        # Setup Solana connection
        self.client = AsyncClient(SOLANA_RPC_URL, commitment=Confirmed)
        
        # Market tracking
        self.active_markets: Dict[int, Dict] = {}
        self.market_counter = 0
        
        print(f"🤖 Manual Market Bot Initialized")
        print(f"Authority: {self.authority_keypair.pubkey()}")
        print(f"Program ID: {PROGRAM_ID}")
        print(f"RPC: {SOLANA_RPC_URL}\n")
    
    def find_pda(self, seeds: List[bytes]) -> tuple[Pubkey, int]:
        """Find a PDA from seeds"""
        pda, bump = Pubkey.find_program_address(seeds, PROGRAM_ID)
        return pda, bump
    
    def encode_string(self, s: str) -> bytes:
        """Encode a string in Rust format (4 bytes length + UTF-8 bytes)"""
        s_bytes = s.encode('utf-8')
        length = len(s_bytes).to_bytes(4, 'little')
        return length + s_bytes
    
    def encode_u64(self, value: int) -> bytes:
        """Encode u64 in little-endian"""
        return value.to_bytes(8, 'little')
    
    def encode_i64(self, value: int) -> bytes:
        """Encode i64 in little-endian"""
        return value.to_bytes(8, 'little', signed=True)
    
    def encode_bool(self, value: bool) -> bytes:
        """Encode bool"""
        return bytes([1 if value else 0])
    
    async def send_transaction(self, instruction: Instruction, signers: List[Keypair]) -> str:
        """Send a transaction and wait for confirmation"""
        try:
            # Get recent blockhash
            blockhash_resp = await self.client.get_latest_blockhash()
            recent_blockhash = blockhash_resp.value.blockhash
            
            # Create transaction
            message = Message.new_with_blockhash(
                [instruction],
                self.authority_keypair.pubkey(),
                recent_blockhash
            )
            
            transaction = Transaction([self.authority_keypair], message, recent_blockhash)
            
            # Send transaction
            tx_opts = TxOpts(skip_preflight=False, preflight_commitment=Confirmed)
            response = await self.client.send_transaction(transaction, opts=tx_opts)
            
            signature = response.value
            print(f"   Transaction: {signature}")
            
            # Wait for confirmation
            await self.client.confirm_transaction(signature, commitment=Confirmed)
            print(f"   ✅ Confirmed!\n")
            
            return str(signature)
            
        except Exception as e:
            print(f"   ❌ Transaction failed: {e}\n")
            raise
    
    async def initialize_program(self):
        """Initialize the prediction market program (one-time setup)"""
        print("📋 Initializing program...")
        
        try:
            config_pda, _ = self.find_pda([CONFIG_SEED])
            
            # Check if already initialized
            account_info = await self.client.get_account_info(config_pda)
            if account_info.value is not None:
                print("   ℹ️  Program already initialized\n")
                return
            
            # Build initialize instruction
            instruction = Instruction(
                program_id=PROGRAM_ID,
                accounts=[
                    AccountMeta(pubkey=config_pda, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=self.authority_keypair.pubkey(), is_signer=True, is_writable=True),
                    AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
                ],
                data=INITIALIZE_DISCRIMINATOR
            )
            
            await self.send_transaction(instruction, [self.authority_keypair])
            print("✅ Program initialized successfully!\n")
            
        except Exception as e:
            print(f"Initialization error: {e}\n")
    
    def get_market_question_from_user(self) -> Optional[Dict]:
        """Get market details from user input"""
        print("\n" + "="*60)
        print("📝 CREATE A NEW MARKET")
        print("="*60)
        
        question = input("\n❓ Question (e.g., 'Will BTC reach $100k by Dec 31?'): ").strip()
        if not question:
            print("❌ Question cannot be empty!")
            return None
        
        if len(question) > 200:
            print(f"❌ Question too long! ({len(question)}/200 chars)")
            return None
        
        description = input("\n📄 Description (what counts as YES/NO): ").strip()
        if len(description) > 1000:
            print(f"❌ Description too long! ({len(description)}/1000 chars)")
            return None
        
        print("\n📂 Categories: Crypto, Sports, Tech, Finance, Weather, Politics, Other")
        category = input("📂 Category: ").strip() or "Other"
        if len(category) > 50:
            category = category[:50]
        
        print("\n⏰ Resolution time (how many days from now?)")
        try:
            days = int(input("   Days from now (1-30): "))
            if days < 1 or days > 30:
                print("❌ Days must be between 1 and 30!")
                return None
        except ValueError:
            print("❌ Invalid number!")
            return None
        
        return {
            'question': question,
            'description': description or f"Market will resolve based on: {question}",
            'category': category,
            'resolution_days': days
        }
    
    async def create_market_on_chain(self, market_data: Dict) -> Optional[int]:
        """Create a prediction market on Solana"""
        market_id = self.market_counter
        self.market_counter += 1
        
        print(f"\n📝 Creating Market #{market_id}...")
        print(f"   Question: {market_data['question']}")
        print(f"   Category: {market_data['category']}")
        
        try:
            # Calculate resolution time
            resolution_time = int(time.time()) + (market_data['resolution_days'] * 86400)
            initial_liquidity = 20_000_000  # 0.02 SOL
            
            # Derive PDAs
            market_pda, _ = self.find_pda([MARKET_SEED, self.encode_u64(market_id)])
            vault_pda, _ = self.find_pda([VAULT_SEED, self.encode_u64(market_id)])
            config_pda, _ = self.find_pda([CONFIG_SEED])
            
            # Build instruction data
            data = (
                CREATE_MARKET_DISCRIMINATOR +
                self.encode_u64(market_id) +
                self.encode_string(market_data['question']) +
                self.encode_string(market_data['description']) +
                self.encode_string(market_data['category']) +
                self.encode_i64(resolution_time) +
                self.encode_u64(initial_liquidity)
            )
            
            # Build instruction
            instruction = Instruction(
                program_id=PROGRAM_ID,
                accounts=[
                    AccountMeta(pubkey=config_pda, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=market_pda, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=True),  # MUST be writable!
                    AccountMeta(pubkey=self.authority_keypair.pubkey(), is_signer=True, is_writable=True),
                    AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
                ],
                data=data
            )
            
            await self.send_transaction(instruction, [self.authority_keypair])
            
            # Store market info
            self.active_markets[market_id] = {
                'question': market_data['question'],
                'description': market_data['description'],
                'category': market_data['category'],
                'resolution_time': resolution_time,
                'market_pda': str(market_pda),
                'vault_pda': str(vault_pda),
                'resolved': False,
                'created_at': datetime.now().isoformat()
            }
            
            print(f"✅ Market #{market_id} created!")
            print(f"   Market PDA: {market_pda}")
            print(f"   Resolves: {datetime.fromtimestamp(resolution_time)}")
            print(f"   View on Explorer:")
            print(f"   https://explorer.solana.com/address/{market_pda}?cluster=devnet\n")
            
            return market_id
            
        except Exception as e:
            print(f"❌ Error creating market: {e}\n")
            return None
    
    async def resolve_market_manually(self, market_id: int, outcome_yes: bool):
        """Manually resolve a market"""
        if market_id not in self.active_markets:
            print(f"❌ Market #{market_id} not found!")
            return
        
        market = self.active_markets[market_id]
        
        if market['resolved']:
            print(f"❌ Market #{market_id} already resolved!")
            return
        
        print(f"\n📊 Resolving Market #{market_id}...")
        print(f"   Question: {market['question']}")
        print(f"   Outcome: {'YES' if outcome_yes else 'NO'}")
        
        try:
            market_pda, _ = self.find_pda([MARKET_SEED, self.encode_u64(market_id)])
            config_pda, _ = self.find_pda([CONFIG_SEED])
            
            # Build instruction data
            data = RESOLVE_MARKET_DISCRIMINATOR + self.encode_bool(outcome_yes)
            
            # Build instruction
            instruction = Instruction(
                program_id=PROGRAM_ID,
                accounts=[
                    AccountMeta(pubkey=config_pda, is_signer=False, is_writable=False),
                    AccountMeta(pubkey=market_pda, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=self.authority_keypair.pubkey(), is_signer=True, is_writable=True),
                ],
                data=data
            )
            
            await self.send_transaction(instruction, [self.authority_keypair])
            
            market['resolved'] = True
            market['outcome'] = outcome_yes
            
            print(f"✅ Market resolved: {'YES' if outcome_yes else 'NO'}\n")
            
        except Exception as e:
            print(f"❌ Error resolving market: {e}\n")
            raise
    
    def list_active_markets(self):
        """Display all active markets"""
        if not self.active_markets:
            print("\n📭 No active markets yet!\n")
            return
        
        print("\n" + "="*60)
        print("📊 ACTIVE MARKETS")
        print("="*60)
        
        for market_id, market in self.active_markets.items():
            status = "✅ RESOLVED" if market['resolved'] else "🔴 ACTIVE"
            outcome = ""
            if market['resolved']:
                outcome = f" → {'YES' if market.get('outcome') else 'NO'}"
            
            resolution_time = datetime.fromtimestamp(market['resolution_time'])
            time_left = resolution_time - datetime.now()
            
            print(f"\n#{market_id} {status}{outcome}")
            print(f"   ❓ {market['question']}")
            print(f"   📂 {market['category']}")
            print(f"   ⏰ Resolves: {resolution_time.strftime('%Y-%m-%d %H:%M')}")
            if not market['resolved']:
                if time_left.total_seconds() > 0:
                    hours = int(time_left.total_seconds() // 3600)
                    print(f"   ⌛ Time left: {hours} hours")
                else:
                    print(f"   ⚠️  Ready to resolve!")
        
        print("\n" + "="*60 + "\n")
    
    async def interactive_menu(self):
        """Interactive menu for manual operation"""
        while True:
            print("\n" + "="*60)
            print("🎮 MANUAL PREDICTION MARKET BOT")
            print("="*60)
            print("\n1. Create a new market")
            print("2. List all markets")
            print("3. Resolve a market")
            print("4. Check balances")
            print("5. Exit")
            
            choice = input("\nChoice (1-5): ").strip()
            
            if choice == "1":
                # Create market
                market_data = self.get_market_question_from_user()
                if market_data:
                    await self.create_market_on_chain(market_data)
                    input("\nPress Enter to continue...")
            
            elif choice == "2":
                # List markets
                self.list_active_markets()
                input("Press Enter to continue...")
            
            elif choice == "3":
                # Resolve market
                self.list_active_markets()
                try:
                    market_id = int(input("Market ID to resolve: "))
                    if market_id not in self.active_markets:
                        print(f"❌ Market #{market_id} not found!")
                        input("Press Enter to continue...")
                        continue
                    
                    if self.active_markets[market_id]['resolved']:
                        print(f"❌ Market #{market_id} already resolved!")
                        input("Press Enter to continue...")
                        continue
                    
                    outcome = input("Outcome (yes/no): ").strip().lower()
                    if outcome not in ['yes', 'no']:
                        print("❌ Invalid outcome! Use 'yes' or 'no'")
                        input("Press Enter to continue...")
                        continue
                    
                    await self.resolve_market_manually(market_id, outcome == 'yes')
                    input("\nPress Enter to continue...")
                    
                except ValueError:
                    print("❌ Invalid market ID!")
                    input("Press Enter to continue...")
            
            elif choice == "4":
                # Check balance
                balance = await self.client.get_balance(self.authority_keypair.pubkey())
                print(f"\n💰 Authority Balance: {balance.value / 1_000_000_000:.4f} SOL")
                input("\nPress Enter to continue...")
            
            elif choice == "5":
                print("\n👋 Goodbye!\n")
                break
            
            else:
                print("❌ Invalid choice!")
                input("Press Enter to continue...")
    
    async def run(self):
        """Main bot loop"""
        print("\n" + "="*60)
        print("🚀 MANUAL PREDICTION MARKET BOT")
        print("="*60)
        print("\nNo AI needed - YOU control everything!")
        print("\n" + "="*60 + "\n")
        
        # Initialize program
        await self.initialize_program()
        
        # Run interactive menu
        try:
            await self.interactive_menu()
        except KeyboardInterrupt:
            print("\n\n👋 Shutting down bot...")


async def main():
    """Entry point"""
    # Load authority keypair path
    keypair_path = os.getenv("AUTHORITY_KEYPAIR", "~/.config/solana/id.json")
    
    # Create bot
    bot = ManualPredictionMarketBot(keypair_path)
    
    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\n\nBot stopped by user")
    finally:
        await bot.client.close()


if __name__ == "__main__":
    asyncio.run(main())