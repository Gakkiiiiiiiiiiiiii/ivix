INSTRUMENTS = {
    "50ETF": {
        "kind": "etf_option",
        "exchange": "SSE",
        "provider_history": "qvix",
        "qvix_symbol": "50ETF",
        "ak_qvix_func": "index_option_50etf_qvix",
        "valid_start": "2015-02-09",
        "output_name": "ivix_50etf.csv",
    },
    "1000INDEX": {
        "kind": "index_option",
        "exchange": "CFFEX",
        "provider_history": "qvix",
        "provider_realtime": "cffex_option_board",
        "qvix_symbol": "Index1000",
        "ak_qvix_func": "index_option_1000index_qvix",
        "ak_board_symbol": "中证1000股指期权",
        "valid_start": "2022-07-22",
        "output_name": "ivix_1000index.csv",
    },
}
