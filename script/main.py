"""
AI Prediction Market Bot - Using solders and solana-py
Creates markets and resolves them using Claude AI
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
from solders.system_program import ID as SYS_PROGRAM_ID, transfer, TransferParams
from solders.transaction import Transaction
from solders.message import Message
from solders.instruction import Instruction, AccountMeta
from solders.hash import Hash
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed, Finalized
from solana.rpc.types import TxOpts

# AI imports
from anthropic import Anthropic

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Configuration
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
PROGRAM_ID = Pubkey.from_string(os.getenv("PROGRAM_ID", "EynCGpDcqKdBZq5YXbtZuFnxXEHzkqDYkXNmstHiDc2C"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Seeds for PDAs
MARKET_SEED = b"market"
VAULT_SEED = b"vault"
USER_POSITION_SEED = b"position"
CONFIG_SEED = b"config"

# Instruction discriminators (from IDL)
INITIALIZE_DISCRIMINATOR = bytes([175, 175, 109, 31, 13, 152, 155, 237])
CREATE_MARKET_DISCRIMINATOR = bytes([103, 226, 97, 235, 200, 188, 251, 254])
BUY_SHARES_DISCRIMINATOR = bytes([40, 239, 138, 154, 8, 37, 106, 108])
RESOLVE_MARKET_DISCRIMINATOR = bytes([155, 23, 80, 173, 46, 74, 23, 239])
CLAIM_WINNINGS_DISCRIMINATOR = bytes([161, 215, 24, 59, 14, 236, 242, 221])


class PredictionMarketBot:
    def __init__(self, authority_keypair_path: str):
        """Initialize the AI bot with authority keypair"""
        # Load authority keypair
        keypair_path = Path(authority_keypair_path).expanduser()
        with open(keypair_path, 'r') as f:
            secret_key = json.load(f)
        self.authority_keypair = Keypair.from_bytes(bytes(secret_key))
        
        # Setup Solana connection
        self.client = AsyncClient(SOLANA_RPC_URL, commitment=Confirmed)
        
        # Setup AI
        self.ai_client = Anthropic(api_key=ANTHROPIC_API_KEY)
        
        # Market tracking
        self.active_markets: Dict[int, Dict] = {}
        self.market_counter = 0
        
        print(f"🤖 Bot initialized")
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
            print(f"   Transaction sent: {signature}")
            
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
    
    async def generate_market_question(self) -> Optional[Dict]:
        """Use AI to generate a prediction market question"""
        print("🤔 Generating market question with AI...")
        
        prompt = """Generate a binary (YES/NO) prediction market question based on current events or upcoming events.

Requirements:
- Must be answerable with YES or NO
- Must have a clear resolution date (within 1-7 days from now)
- Must be verifiable using public information (news, official data, etc.)
- Should be interesting and relevant
- Should be specific and unambiguous

Return ONLY a JSON object with this exact structure:
{
    "question": "Will X happen by Y date?",
    "description": "Detailed description including what counts as YES/NO and data sources for verification",
    "category": "Crypto",
    "resolution_days": 3
}

Categories: Crypto, Sports, Tech, Finance, Weather, Politics

Examples:
- "Will Bitcoin close above $95,000 on October 20, 2025?"
- "Will it rain in San Francisco tomorrow?"
- "Will SOL reach $200 by end of week?"

Generate ONE new question now:"""

        try:
            message = self.ai_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )
            
            response_text = message.content[0].text
            
            # Extract JSON
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                market_data = json.loads(json_match.group())
                print(f"   ✅ Generated: {market_data['question'][:60]}...\n")
                return market_data
            else:
                print("   ❌ Failed to extract JSON from AI response\n")
                return None
                
        except Exception as e:
            print(f"   ❌ Error generating question: {e}\n")
            return None
    
    async def create_market_on_chain(self, market_data: Dict) -> Optional[int]:
        """Create a prediction market on Solana"""
        market_id = self.market_counter
        self.market_counter += 1
        
        print(f"📝 Creating Market #{market_id}...")
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
                    AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=False),
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
            print(f"   Resolution: {datetime.fromtimestamp(resolution_time)}\n")
            
            return market_id
            
        except Exception as e:
            print(f"❌ Error creating market: {e}\n")
            return None
    
    async def resolve_market_with_ai(self, market_id: int) -> Optional[bool]:
        """Use AI to determine the outcome of a market"""
        if market_id not in self.active_markets:
            print(f"Market #{market_id} not found")
            return None
        
        market = self.active_markets[market_id]
        
        # Check if ready to resolve
        current_time = int(time.time())
        if current_time < market['resolution_time']:
            print(f"Market #{market_id} not ready for resolution yet")
            return None
        
        if market['resolved']:
            print(f"Market #{market_id} already resolved")
            return None
        
        print(f"🔍 Resolving Market #{market_id} with AI...")
        print(f"   Question: {market['question']}")
        
        resolution_prompt = f"""You are resolving a prediction market. Research and determine if the answer is YES or NO.

Question: {market['question']}
Description: {market['description']}
Category: {market['category']}
Resolution Date: {datetime.fromtimestamp(market['resolution_time'])}

Instructions:
1. Based on your knowledge, determine the factual outcome
2. Make a definitive YES or NO determination
3. Explain your reasoning briefly

Return ONLY a JSON object:
{{
    "outcome": "YES" or "NO",
    "confidence": 0.0 to 1.0,
    "reasoning": "Brief explanation of why you chose this outcome"
}}"""

        try:
            message = self.ai_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                messages=[{"role": "user", "content": resolution_prompt}]
            )
            
            response_text = message.content[0].text
            print(f"   AI Response: {response_text[:200]}...\n")
            
            # Extract JSON
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                resolution_data = json.loads(json_match.group())
                outcome_yes = resolution_data['outcome'].upper() == "YES"
                
                print(f"   📊 Outcome: {resolution_data['outcome']}")
                print(f"   Confidence: {resolution_data['confidence']:.0%}")
                print(f"   Reasoning: {resolution_data['reasoning']}\n")
                
                # Submit resolution to blockchain
                await self.submit_resolution(market_id, outcome_yes)
                
                market['resolved'] = True
                market['outcome'] = outcome_yes
                market['resolution_data'] = resolution_data
                
                return outcome_yes
            else:
                print("   ❌ Failed to extract resolution JSON\n")
                return None
                
        except Exception as e:
            print(f"   ❌ Error resolving with AI: {e}\n")
            return None
    
    async def submit_resolution(self, market_id: int, outcome_yes: bool):
        """Submit market resolution to blockchain"""
        print(f"📤 Submitting resolution to blockchain...")
        
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
            print(f"✅ Resolution submitted: {'YES' if outcome_yes else 'NO'}\n")
            
        except Exception as e:
            print(f"❌ Error submitting resolution: {e}\n")
            raise
    
    async def monitor_and_resolve_markets(self):
        """Continuously monitor markets and resolve them when time comes"""
        print(" Starting market resolution monitor...\n")
        
        while True:
            current_time = int(time.time())
            
            for market_id, market in list(self.active_markets.items()):
                if not market['resolved'] and current_time >= market['resolution_time']:
                    print(f"Market #{market_id} ready for resolution!")
                    await self.resolve_market_with_ai(market_id)
                    await asyncio.sleep(2)  # Rate limiting
            
            # Check every 60 seconds
            await asyncio.sleep(60)
    
    async def run(self):
        """Main bot loop"""
        print("\n" + "="*60)
        print(" AI PREDICTION MARKET BOT STARTING")
        print("="*60 + "\n")
        
        # Initialize program
        await self.initialize_program()
        
        # Create initial markets
        print("📝 Generating initial markets...\n")
        for i in range(3):
            market_data = await self.generate_market_question()
            if market_data:
                await self.create_market_on_chain(market_data)
                await asyncio.sleep(2)  # Rate limiting
        
        # Start monitoring task
        print("="*60)
        print("🔄 Bot is now running - monitoring markets...")
        print("="*60 + "\n")
        
        monitor_task = asyncio.create_task(self.monitor_and_resolve_markets())
        
        # Create new markets periodically
        try:
            while True:
                await asyncio.sleep(3600)  # Every hour
                
                print("\n📝 Generating new market...\n")
                market_data = await self.generate_market_question()
                if market_data:
                    await self.create_market_on_chain(market_data)
        
        except KeyboardInterrupt:
            print("\n\n👋 Shutting down bot...")
            monitor_task.cancel()


async def main():
    """Entry point"""
    # Load authority keypair path
    keypair_path = os.getenv("AUTHORITY_KEYPAIR", "~/.config/solana/id.json")
    
    # Create bot
    bot = PredictionMarketBot(keypair_path)
    
    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\n\nBot stopped by user")
    finally:
        await bot.client.close()


if __name__ == "__main__":
    asyncio.run(main())