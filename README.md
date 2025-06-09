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
pip install web3 requests python-dotenv
```

### 3. Configure Your Environment Variables

Create a file named `.env` in the project root with the following content:
```
INFURA_URL=https://mainnet.infura.io/v3/YOUR_INFURA_PROJECT_ID
```
Replace `YOUR_INFURA_PROJECT_ID` with your actual Infura Project ID. You can get one for free at [infura.io](https://infura.io/).

> **Note:** The `.env` file is included in `.gitignore` and will not be tracked by git, keeping your API key secure.

## Scripts Overview

### check_balance.py
- **Purpose:**
  - Automatically detects the type of cryptocurrency (Bitcoin, Ethereum, or Monero) from a wallet address and checks its balance (when possible).
- **How it works:**
  - Prompts the user to enter a wallet address.
  - Uses the `detect_coin.py` script to identify the coin type.
  - For Ethereum: Connects to the Ethereum blockchain using your Infura API key and retrieves the balance in Ether.
  - For Bitcoin: Uses the Blockstream public API to retrieve the balance in BTC.
  - For Monero: Explains that public balance queries are not possible due to privacy features.
- **Usage:**
  1. Make sure your `.env` file is configured with your Infura URL.
  2. Run the script:
     ```powershell
     python check_balance.py
     ```
  3. Enter the wallet address when prompted. The script will detect the coin and show the balance if possible.

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

## Security & .gitignore

- The `.env` file (containing your Infura API key) and the `venv` folder are ignored by git for security and cleanliness.
- Python cache files and folders (`__pycache__`, `*.pyc`, etc.) are also ignored.

## License

This project is for educational and research purposes. Use at your own risk.
