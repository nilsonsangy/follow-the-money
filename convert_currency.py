import requests

SUPPORTED_COINS = {
    'BTC': 'bitcoin',
    'ETH': 'ethereum',
    'XMR': 'monero',
}

FIAT_CURRENCIES = ['usd', 'brl']


def get_coin_price(coin_symbol, fiat):
    """
    Fetches the current price of a cryptocurrency in the specified fiat currency using CoinGecko API.
    Args:
        coin_symbol (str): Symbol of the coin (e.g., 'BTC', 'ETH', 'XMR')
        fiat (str): Fiat currency ('usd' or 'brl')
    Returns:
        float: Current price
    Raises:
        Exception: If the API call fails or coin is not supported
    """
    coin_id = SUPPORTED_COINS.get(coin_symbol.upper())
    if not coin_id:
        raise Exception('Coin not supported.')
    if fiat.lower() not in FIAT_CURRENCIES:
        raise Exception('Fiat currency not supported.')
    url = f'https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies={fiat}'
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception('Failed to fetch price from CoinGecko.')
    data = response.json()
    return data[coin_id][fiat.lower()]


def main():
    print('Supported coins: BTC, ETH, XMR')
    coin = input('Enter the coin symbol: ').upper()
    amount = float(input(f'Enter the amount of {coin}: '))
    for fiat in FIAT_CURRENCIES:
        try:
            price = get_coin_price(coin, fiat)
            total = amount * price
            # Format with thousands separator as ',' and decimal as '.'
            formatted_total = f'{total:,.2f}'
            formatted_price = f'{price:,.2f}'
            print(f'{amount} {coin} = {formatted_total} {fiat.upper()} (1 {coin} = {formatted_price} {fiat.upper()})')
        except Exception as e:
            print(f'Error converting to {fiat.upper()}: {e}')

if __name__ == '__main__':
    main()
