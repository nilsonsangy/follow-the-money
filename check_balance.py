import os
import requests
from web3 import Web3
from detect_coin import detect_coin  # Import the coin detection function
from convert_currency import get_coin_price

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get the Infura URL from environment variables
INFURA_URL = os.getenv('INFURA_URL')
# Create a Web3 instance using the HTTP provider
w3 = Web3(Web3.HTTPProvider(INFURA_URL))

def get_eth_balance(address):
    """
    Returns the Ether balance of a given Ethereum address.
    Args:
        address (str): Ethereum wallet address
    Returns:
        float: Balance in Ether
    Raises:
        ValueError: If the address is invalid
    """
    # Use Web3's built-in is_checksum_address or is_address depending on web3.py version
    if not Web3.is_address(address):
        raise ValueError('Invalid Ethereum address')
    # Get balance in Wei (smallest unit of Ether)
    balance_wei = w3.eth.get_balance(address)
    # Convert Wei to Ether
    balance_eth = Web3.from_wei(balance_wei, 'ether')
    # Get ETH price in USD
    try:
        eth_price_usd = get_coin_price('ETH', 'usd')
        value_usd = float(balance_eth) * eth_price_usd
        print(f'Wallet balance: {balance_eth} ETH (~${value_usd:,.2f} USD)')
    except Exception as e:
        print(f'Could not fetch ETH price in USD: {e}')
    return balance_eth

def get_btc_balance(address):
    """
    Returns the Bitcoin balance of a given Bitcoin address using Blockstream API.
    Args:
        address (str): Bitcoin wallet address
    Returns:
        float: Balance in BTC
    Raises:
        Exception: If the address is invalid or API fails
    """
    url = f'https://blockstream.info/api/address/{address}'
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception('Invalid Bitcoin address or API error')
    data = response.json()
    # Balance is in satoshis, convert to BTC
    balance_btc = data['chain_stats']['funded_txo_sum'] - data['chain_stats']['spent_txo_sum']
    balance_btc = balance_btc / 1e8
    # Get BTC price in USD
    try:
        btc_price_usd = get_coin_price('BTC', 'usd')
        value_usd = float(balance_btc) * btc_price_usd
        print(f'Wallet balance: {balance_btc} BTC (~${value_usd:,.2f} USD)')
    except Exception as e:
        print(f'Could not fetch BTC price in USD: {e}')
    return balance_btc

def get_xmr_balance(address):
    """
    Monero does not support public balance queries due to privacy features.
    This function will always return a message explaining this limitation.
    """
    try:
        xmr_price_usd = get_coin_price('XMR', 'usd')
        print(f'If you know your XMR balance, 1 XMR = ${xmr_price_usd:,.2f} USD')
    except Exception as e:
        print(f'Could not fetch XMR price in USD: {e}')
    raise Exception('Monero balances cannot be checked publicly due to privacy features.')

if __name__ == '__main__':
    # Prompt the user to enter a wallet address
    address = input('Enter the wallet address: ')
    # Automatically detect the coin type
    coin = detect_coin(address)
    # Print detected coin in the order: Bitcoin, Ethereum, Monero
    if coin == 'Bitcoin':
        print('Detected coin: Bitcoin')
    elif coin == 'Ethereum':
        print('Detected coin: Ethereum')
    elif coin == 'Monero':
        print('Detected coin: Monero')
    else:
        print(f'Detected coin: {coin}')
    try:
        if coin == 'Bitcoin':
            get_btc_balance(address)
        elif coin == 'Ethereum':
            get_eth_balance(address)
        elif coin == 'Monero':
            get_xmr_balance(address)
        else:
            print('Unsupported or unknown coin type.')
    except Exception as e:
        print(f'Error: {e}')
