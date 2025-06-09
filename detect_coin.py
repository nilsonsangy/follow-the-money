import re

# Regular expressions for common cryptocurrency address formats
ADDRESS_PATTERNS = {
    'Bitcoin': re.compile(r'^(1|3|bc1)[a-zA-HJ-NP-Z0-9]{25,39}$'),  # Bitcoin addresses start with 1, 3, or bc1 and are 26-42 chars
    'Ethereum': re.compile(r'^(0x)[0-9a-fA-F]{40}$'),  # Ethereum addresses start with 0x and are 42 chars
    'Litecoin': re.compile(r'^(L|M|ltc1)[a-zA-HJ-NP-Z0-9]{25,39}$'),  # Litecoin addresses start with L, M, or ltc1 and are 26-42 chars
    'Monero': re.compile(r'^(4|8)[0-9AB][1-9A-HJ-NP-Za-km-z]{93}$'),  # Monero addresses start with 4 or 8 and are 95 chars
    # Add more coins and patterns as needed
}

def detect_coin(address):
    """
    Detects the cryptocurrency coin based on the wallet address format.
    Args:
        address (str): The wallet address to check
    Returns:
        str: The name of the detected coin, or 'Unknown' if not matched
    """
    for coin, pattern in ADDRESS_PATTERNS.items():
        if pattern.match(address):
            return coin
    return 'Unknown'

if __name__ == '__main__':
    # Prompt the user to enter a wallet address
    address = input('Enter the wallet address: ')
    # Detect and print the coin type
    coin = detect_coin(address)
    print(f'This address is likely for: {coin}')
