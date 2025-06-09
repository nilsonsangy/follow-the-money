# N1Crypto

N1Crypto is a powerful and extensible crypto analysis toolkit built for blockchain enthusiasts, analysts, and developers.

## Getting Started

This project requires Python 3.7 or higher. It is recommended to use a virtual environment to manage dependencies.

### 1. Create and Activate a Virtual Environment

On Windows (using PowerShell):
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

On Linux or macOS:
```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install Required Libraries

Install the required Python libraries using pip:
```powershell
pip install web3
```

> **Note:** The `detect_coin.py` script uses only the standard library (no extra dependencies). The `check_balance.py` script requires the `web3` library.

## Scripts Overview

### check_balance.py
- **Purpose:**
  - Checks the Ether (ETH) balance of a given Ethereum wallet address.
- **How it works:**
  - Prompts the user to enter an Ethereum address.
  - Connects to the Ethereum blockchain using a provider (e.g., Infura).
  - Retrieves and displays the balance in Ether.
- **Usage:**
  1. Edit the `INFURA_URL` variable in the script and insert your Infura Project ID or another Ethereum node provider URL.
  2. Run the script:
     ```powershell
     python check_balance.py
     ```
  3. Enter the Ethereum wallet address when prompted.

### detect_coin.py
- **Purpose:**
  - Detects the type of cryptocurrency (Bitcoin, Ethereum, Litecoin, Monero) based on the wallet address format.
- **How it works:**
  - Prompts the user to enter a wallet address.
  - Uses regular expressions to match the address format against known patterns for supported coins.
  - Prints the likely coin type or 'Unknown' if the address does not match any known pattern.
- **Usage:**
  1. Run the script:
     ```powershell
     python detect_coin.py
     ```
  2. Enter the wallet address when prompted.

## Adding More Coins

To support more cryptocurrencies in `detect_coin.py`, add new regular expressions to the `ADDRESS_PATTERNS` dictionary following the existing examples and comments.

## License

This project is for educational and research purposes. Use at your own risk.
