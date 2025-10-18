"""
Groq AI Demo Bot - MVP Showcase (WITH ON-CHAIN MARKET LISTING!)
- Creates impressive demo markets using FREE Groq AI
- Lists ALL markets from blockchain
- Fast generation (Groq is fastest AI)
- Perfect for demos, pitches, presentations
- NO COST - completely FREE!
"""

import os
import json
import time
import asyncio
import random
import re
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

# Groq AI (FREE!)
from groq import Groq

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Configuration
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
PROGRAM_ID = Pubkey.from_string(os.getenv("PROGRAM_ID", "EynCGpDcqKdBZq5YXbtZuFnxXEHzkqDYkXNmstHiDc2C"))
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Seeds for PDAs
MARKET_SEED = b"market"
VAULT_SEED = b"vault"
CONFIG_SEED = b"config"

# Instruction discriminators
INITIALIZE_DISCRIMINATOR = bytes([175, 175, 109, 31, 13, 152, 155, 237])
CREATE_MARKET_DISCRIMINATOR = bytes([103, 226, 97, 235, 200, 188, 251, 254])
RESOLVE_MARKET_DISCRIMINATOR = bytes([155, 23, 80, 173, 46, 74, 23, 239])

# Account discriminators (for identifying account types)
MARKET_DISCRIMINATOR = bytes([219, 190, 213, 55, 0, 227, 198, 154])


class GroqDemoBot:
    def __init__(self, authority_keypair_path: str):
        """Initialize demo bot with Groq AI (FREE!)"""
        keypair_path = Path(authority_keypair_path).expanduser()
        with open(keypair_path, 'r') as f:
            secret_key = json.load(f)
        self.authority_keypair = Keypair.from_bytes(bytes(secret_key))
        
        self.client = AsyncClient(SOLANA_RPC_URL, commitment=Confirmed)
        self.ai = Groq(api_key=GROQ_API_KEY)
        
        self.active_markets: Dict[int, Dict] = {}
        self.market_counter = 0
        
        print("="*60)
        print("🎬 GROQ AI DEMO BOT - MVP SHOWCASE")
        print("="*60)
        print(f"💰 Cost: FREE (Groq AI)")
        print(f"⚡ Speed: Fastest AI available")
        print(f"🎯 Purpose: Demo & Showcase")
        print(f"👤 Authority: {self.authority_keypair.pubkey()}")
        print(f"📡 RPC: {SOLANA_RPC_URL}")
        print("="*60 + "\n")
    
    def find_pda(self, seeds: List[bytes]) -> tuple:
        """Find a PDA from seeds"""
        pda, bump = Pubkey.find_program_address(seeds, PROGRAM_ID)
        return pda, bump
    
    def encode_string(self, s: str) -> bytes:
        """Encode a string in Rust format"""
        s_bytes = s.encode('utf-8')
        length = len(s_bytes).to_bytes(4, 'little')
        return length + s_bytes
    
    def encode_u64(self, value: int) -> bytes:
        """Encode u64"""
        return value.to_bytes(8, 'little')
    
    def encode_i64(self, value: int) -> bytes:
        """Encode i64"""
        return value.to_bytes(8, 'little', signed=True)
    
    def encode_bool(self, value: bool) -> bytes:
        """Encode bool"""
        return bytes([1 if value else 0])
    
    async def send_transaction(self, instruction: Instruction, signers: List[Keypair]) -> str:
        """Send a transaction"""
        try:
            blockhash_resp = await self.client.get_latest_blockhash()
            recent_blockhash = blockhash_resp.value.blockhash
            
            message = Message.new_with_blockhash(
                [instruction],
                self.authority_keypair.pubkey(),
                recent_blockhash
            )
            
            transaction = Transaction([self.authority_keypair], message, recent_blockhash)
            
            tx_opts = TxOpts(skip_preflight=False, preflight_commitment=Confirmed)
            response = await self.client.send_transaction(transaction, opts=tx_opts)
            
            signature = response.value
            print(f"   📝 Transaction: {signature}")
            
            await self.client.confirm_transaction(signature, commitment=Confirmed)
            print(f"   ✅ Confirmed!\n")
            
            return str(signature)
            
        except Exception as e:
            print(f"   ❌ Transaction failed: {e}\n")
            raise
    
    async def initialize_program(self):
        """Initialize the prediction market program"""
        print("📋 Initializing program...\n")
        
        try:
            config_pda, _ = self.find_pda([CONFIG_SEED])
            
            account_info = await self.client.get_account_info(config_pda)
            if account_info.value is not None:
                print("   ℹ️  Program already initialized")
                
                data = account_info.value.data
                if len(data) >= 48:
                    market_count_bytes = data[40:48]
                    self.market_counter = int.from_bytes(market_count_bytes, 'little')
                    print(f"   📊 Starting from market #{self.market_counter}\n")
                return
            
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
            print("✅ Program initialized!\n")
            
        except Exception as e:
            print(f"❌ Initialization error: {e}\n")
    
    def ask_groq(self, prompt: str, temperature: float = 0.8) -> str:
        """Ask Groq AI (FREE & FAST!)"""
        try:
            response = self.ai.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=1000
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            print(f"❌ Groq error: {e}")
            return None
    
    def generate_demo_market(self, category: str = None) -> Optional[Dict]:
        """Generate a demo market question using Groq AI"""
        
        categories = ["Crypto", "Sports", "Tech", "Finance", "Weather", "Politics"]
        if not category:
            category = random.choice(categories)
        
        print(f"🎨 Generating {category} market with Groq AI...")
        
        prompt = f"""Create ONE exciting binary prediction market question for a demo/MVP showcase.

Category: {category}

Requirements:
- Must be a YES/NO question
- Should be impressive and engaging
- Must have clear resolution criteria
- Should resolve in 1-7 days
- Make it realistic and interesting

Return ONLY valid JSON (no markdown, no code blocks):
{{
    "question": "Will X happen by Y date?",
    "description": "Clear explanation of what YES and NO mean",
    "category": "{category}",
    "resolution_days": 3,
    "wow_factor": "Why this market is interesting"
}}"""

        response = self.ask_groq(prompt)
        
        if not response:
            return self.get_fallback_market(category)
        
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                market_data = json.loads(json_match.group())
                print(f"   ✅ Generated: {market_data['question'][:70]}...")
                print(f"   ⭐ Wow: {market_data.get('wow_factor', 'N/A')[:60]}...\n")
                return market_data
            else:
                return self.get_fallback_market(category)
                
        except Exception as e:
            print(f"   ❌ Error parsing: {e}\n")
            return self.get_fallback_market(category)
    
    def get_fallback_market(self, category: str) -> Dict:
        """Fallback demo markets"""
        fallbacks = {
            "Crypto": {
                "question": "Will Bitcoin reach $100,000 by end of month?",
                "description": "Resolves YES if BTC closes above $100k on CoinMarketCap",
                "category": "Crypto",
                "resolution_days": 7,
                "wow_factor": "Major price milestone!"
            },
            "Sports": {
                "question": "Will Manchester United win their next match?",
                "description": "Resolves YES if Man United wins",
                "category": "Sports",
                "resolution_days": 3,
                "wow_factor": "Premier League excitement!"
            },
            "Tech": {
                "question": "Will Apple announce new iPhone this week?",
                "description": "Resolves YES if official announcement",
                "category": "Tech",
                "resolution_days": 7,
                "wow_factor": "Major tech launch!"
            }
        }
        return fallbacks.get(category, fallbacks["Crypto"])
    
    async def create_market_on_chain(self, market_data: Dict) -> Optional[int]:
        """Create market on Solana blockchain"""
        market_id = self.market_counter
        self.market_counter += 1
        
        print(f"📝 Creating Market #{market_id} on-chain...")
        print(f"   ❓ {market_data['question']}")
        print(f"   📂 Category: {market_data['category']}")
        
        try:
            resolution_time = int(time.time()) + (int(market_data['resolution_days']) * 86400)
            initial_liquidity = 20_000_000
            
            market_pda, _ = self.find_pda([MARKET_SEED, self.encode_u64(market_id)])
            vault_pda, _ = self.find_pda([VAULT_SEED, self.encode_u64(market_id)])
            config_pda, _ = self.find_pda([CONFIG_SEED])
            
            data = (
                CREATE_MARKET_DISCRIMINATOR +
                self.encode_u64(market_id) +
                self.encode_string(market_data['question']) +
                self.encode_string(market_data['description']) +
                self.encode_string(market_data['category']) +
                self.encode_i64(resolution_time) +
                self.encode_u64(initial_liquidity)
            )
            
            instruction = Instruction(
                program_id=PROGRAM_ID,
                accounts=[
                    AccountMeta(pubkey=config_pda, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=market_pda, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=self.authority_keypair.pubkey(), is_signer=True, is_writable=True),
                    AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
                ],
                data=data
            )
            
            await self.send_transaction(instruction, [self.authority_keypair])
            
            self.active_markets[market_id] = {
                'question': market_data['question'],
                'description': market_data['description'],
                'category': market_data['category'],
                'resolution_time': resolution_time,
                'market_pda': str(market_pda),
                'vault_pda': str(vault_pda),
                'resolved': False,
                'created_at': datetime.now().isoformat(),
                'wow_factor': market_data.get('wow_factor', '')
            }
            
            print(f"✅ Market #{market_id} created!")
            print(f"   ⏰ Resolves: {datetime.fromtimestamp(resolution_time).strftime('%Y-%m-%d %H:%M')}")
            print(f"   🔗 Explorer: https://explorer.solana.com/address/{market_pda}?cluster=devnet\n")
            
            return market_id
            
        except Exception as e:
            print(f"❌ Error creating market: {e}\n")
            self.market_counter -= 1
            return None
    
    async def fetch_all_markets_from_chain(self) -> Dict[int, Dict]:
        """Fetch ALL markets from blockchain by trying sequential market IDs"""
        print("🔍 Fetching all markets from blockchain...\n")
        
        try:
            # We know from config how many markets exist
            config_pda, _ = self.find_pda([CONFIG_SEED])
            config_info = await self.client.get_account_info(config_pda)
            
            max_markets = 0
            if config_info.value:
                data = config_info.value.data
                if len(data) >= 48:
                    max_markets = int.from_bytes(data[40:48], 'little')
            
            if max_markets == 0:
                print("   ℹ️  No markets created yet\n")
                return {}
            
            print(f"   📊 Checking {max_markets} potential markets...")
            
            chain_markets: Dict[int, Dict] = {}
            
            # Fetch each market individually
            for market_id in range(max_markets):
                try:
                    market_pda, _ = self.find_pda([MARKET_SEED, self.encode_u64(market_id)])
                    account_info = await self.client.get_account_info(market_pda)
                    
                    if account_info.value and len(account_info.value.data) >= 16:
                        data = account_info.value.data
                        
                        # Verify it's a market account
                        if data[:8] == MARKET_DISCRIMINATOR:
                            # Parse basic info
                            offset = 16  # After discriminator + market_id
                            offset += 32  # Skip authority
                            
                            # Try to parse question (string = 4 bytes length + content)
                            try:
                                question_len = int.from_bytes(data[offset:offset+4], 'little')
                                offset += 4
                                
                                if question_len > 0 and question_len < 500:  # Sanity check
                                    question = data[offset:offset+question_len].decode('utf-8', errors='ignore')
                                    offset += question_len
                                else:
                                    question = f"Market #{market_id}"
                                    
                                # Try to parse description
                                desc_len = int.from_bytes(data[offset:offset+4], 'little')
                                offset += 4
                                offset += desc_len  # Skip description
                                
                                # Try to parse category
                                cat_len = int.from_bytes(data[offset:offset+4], 'little')
                                offset += 4
                                
                                if cat_len > 0 and cat_len < 100:
                                    category = data[offset:offset+cat_len].decode('utf-8', errors='ignore')
                                    offset += cat_len
                                else:
                                    category = "Unknown"
                                    offset += cat_len
                                
                                # Parse resolution_time (i64)
                                resolution_time = int.from_bytes(data[offset:offset+8], 'little', signed=True)
                                offset += 8
                                
                                # Skip created_at
                                offset += 8
                                
                                # Skip liquidity values
                                offset += 8 * 5
                                
                                # Parse resolved (bool)
                                resolved = data[offset] == 1
                                
                            except Exception:
                                question = f"Market #{market_id}"
                                category = "On-Chain"
                                resolution_time = 0
                                resolved = False
                            
                            chain_markets[market_id] = {
                                'question': question,
                                'description': "View on explorer for details",
                                'category': category,
                                'resolution_time': resolution_time,
                                'market_pda': str(market_pda),
                                'resolved': resolved,
                            }
                
                except Exception:
                    continue
            
            print(f"   ✅ Found {len(chain_markets)} markets on-chain\n")
            return chain_markets
            
        except Exception as e:
            print(f"   ❌ Error fetching: {e}\n")
            return {}
    
    async def display_active_markets(self):
        """Display all markets (local + on-chain)"""
        
        # Fetch from chain
        chain_markets = await self.fetch_all_markets_from_chain()
        
        # Merge with local
        all_markets = chain_markets.copy()
        for market_id, local_market in self.active_markets.items():
            all_markets[market_id] = local_market
        
        if not all_markets:
            print("📭 No markets yet!\n")
            return
        
        print("\n" + "="*60)
        print("📊 ALL MARKETS (Local + On-Chain)")
        print("="*60 + "\n")
        
        for market_id in sorted(all_markets.keys()):
            market = all_markets[market_id]
            status = "🔴 ACTIVE" if not market['resolved'] else "✅ RESOLVED"
            source = "(This Session)" if market_id in self.active_markets else "(From Chain)"
            
            print(f"#{market_id} {status} {source}")
            print(f"   ❓ {market['question']}")
            print(f"   📂 {market['category']}")
            
            if market['resolution_time'] > 0:
                res_time = datetime.fromtimestamp(market['resolution_time']).strftime('%Y-%m-%d %H:%M')
                print(f"   ⏰ Resolves: {res_time}")
            
            print(f"   🔗 PDA: {market['market_pda']}\n")
        
        print("="*60 + "\n")
    
    async def create_demo_showcase(self, num_markets: int = 5):
        """Create multiple markets for demo"""
        print("🎬 Creating impressive demo showcase...\n")
        
        categories = ["Crypto", "Sports", "Tech", "Finance", "Politics"]
        
        for i in range(num_markets):
            category = categories[i % len(categories)]
            market_data = self.generate_demo_market(category)
            
            if market_data:
                await self.create_market_on_chain(market_data)
                await asyncio.sleep(1)
            
            print(f"Progress: {i+1}/{num_markets}\n")
        
        print("="*60)
        print("🎉 DEMO SHOWCASE READY!")
        print("="*60)
        print(f"✅ Created {num_markets} impressive markets")
        print(f"💰 All using FREE Groq AI")
        print(f"⚡ Lightning fast generation")
        print("="*60 + "\n")
    
    async def interactive_menu(self):
        """Interactive menu"""
        while True:
            print("\n" + "="*60)
            print("🎮 DEMO BOT MENU")
            print("="*60)
            print("1. Generate 1 random market")
            print("2. Generate 5 markets (quick showcase)")
            print("3. Generate 10 markets (full demo)")
            print("4. List ALL markets (fetches from chain) 📡")
            print("5. Generate specific category")
            print("6. Exit")
            print("="*60)
            
            try:
                choice = input("\nChoice (1-6): ").strip()
                
                if choice == "1":
                    market_data = self.generate_demo_market()
                    if market_data:
                        await self.create_market_on_chain(market_data)
                
                elif choice == "2":
                    await self.create_demo_showcase(5)
                
                elif choice == "3":
                    await self.create_demo_showcase(10)
                
                elif choice == "4":
                    await self.display_active_markets()
                    input("Press Enter to continue...")
                
                elif choice == "5":
                    categories = ["Crypto", "Sports", "Tech", "Finance", "Weather", "Politics"]
                    print(f"\nCategories: {', '.join(categories)}")
                    category = input("Choose category: ").strip()
                    market_data = self.generate_demo_market(category)
                    if market_data:
                        await self.create_market_on_chain(market_data)
                
                elif choice == "6":
                    print("\n👋 Thanks for using Groq Demo Bot!")
                    break
                
                else:
                    print("❌ Invalid choice")
                    
            except KeyboardInterrupt:
                print("\n\n👋 Exiting...")
                break
    
    async def run(self):
        """Main bot entry"""
        await self.initialize_program()
        await self.interactive_menu()


async def main():
    """Entry point"""
    keypair_path = os.getenv("AUTHORITY_KEYPAIR", "~/.config/solana/id.json")
    
    if not GROQ_API_KEY:
        print("="*60)
        print("❌ GROQ_API_KEY not found in .env!")
        print("="*60)
        print("\n🚀 Get your FREE Groq API key:")
        print("   1. Go to: https://console.groq.com")
        print("   2. Sign up (no credit card!)")
        print("   3. Create API key")
        print("   4. Add to .env: GROQ_API_KEY=gsk_xxxxx\n")
        print("="*60 + "\n")
        return
    
    bot = GroqDemoBot(keypair_path)
    
    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\n\n👋 Demo bot stopped")
    finally:
        await bot.client.close()


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║       🎬 GROQ AI PREDICTION MARKET DEMO BOT 🎬          ║
║                                                          ║
║  💰 Cost: FREE                                           ║
║  ⚡ Speed: Lightning fast                                ║
║  🎯 Purpose: MVP Showcase & Demos                        ║
║  📡 Now lists ALL markets from blockchain!               ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
""")
    asyncio.run(main())