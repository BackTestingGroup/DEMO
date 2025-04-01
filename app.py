import streamlit as st
import pandas as pd
import numpy as np
import ccxt
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import time
import os

# 앱 타이틀 설정
st.set_page_config(page_title="코인 백테스팅 시스템", layout="wide")
st.title("코인 백테스팅 시스템")

# 캐시 디렉토리 생성
if not os.path.exists('cache'):
    os.makedirs('cache')

# 지원되는 거래소 목록
SUPPORTED_EXCHANGES = {
    "Binance US": "binanceus",
    "Binance": "binance",
    "Upbit": "upbit",
    "Kraken": "kraken",
    "KuCoin": "kucoin"
}

# 거래소별 기본 코인 목록
EXCHANGE_COINS = {
    "binanceus": ["BTC/USDT", "ETH/USDT", "ADA/USDT", "SOL/USDT", "XRP/USDT"],
    "binance": ["BTC/USDT", "ETH/USDT", "ADA/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT", "DOT/USDT"],
    "upbit": ["BTC/KRW", "ETH/KRW", "XRP/KRW", "ADA/KRW", "SOL/KRW"],
    "kraken": ["BTC/USD", "ETH/USD", "ADA/USD", "SOL/USD", "XRP/USD"],
    "kucoin": ["BTC/USDT", "ETH/USDT", "ADA/USDT", "SOL/USDT", "XRP/USDT"]
}

# 거래소별 기본 수수료 (현물 거래 기준)
EXCHANGE_FEES = {
    "binanceus": {
        "maker": 0.0010,  # 0.10%
        "taker": 0.0010,  # 0.10%
        "description": "Binance US 기본 수수료율"
    },
    "binance": {
        "maker": 0.0010,  # 0.10%
        "taker": 0.0010,  # 0.10%
        "description": "Binance 기본 수수료율"
    },
    "upbit": {
        "maker": 0.0005,  # 0.05%
        "taker": 0.0005,  # 0.05%
        "description": "Upbit 기본 수수료율"
    },
    "kraken": {
        "maker": 0.0016,  # 0.16%
        "taker": 0.0026,  # 0.26%
        "description": "Kraken 기본 수수료율"
    },
    "kucoin": {
        "maker": 0.0010,  # 0.10%
        "taker": 0.0010,  # 0.10%
        "description": "KuCoin 기본 수수료율"
    }
}

# 거래소별 평균 슬리피지 (일반적인 시장 조건)
EXCHANGE_SLIPPAGE = {
    "binanceus": 0.0010,  # 0.10%
    "binance": 0.0005,    # 0.05% (더 높은 유동성)
    "upbit": 0.0010,      # 0.10%
    "kraken": 0.0015,     # 0.15%
    "kucoin": 0.0010      # 0.10%
}

# 코인별 변동성 계수 (더 높은 값 = 더 높은 변동성 = 더 높은 슬리피지)
COIN_VOLATILITY = {
    "BTC": 1.0,      # 기준
    "ETH": 1.1,      # BTC보다 10% 더 변동적
    "ADA": 1.3,
    "SOL": 1.4,
    "XRP": 1.2,
    "DOGE": 1.5,
    "DOT": 1.3
}

# 거래량 수준에 따른 슬리피지 조정
def adjust_slippage_by_volume(base_slippage, volume, avg_volume):
    """거래량에 따라 슬리피지 조정"""
    if volume <= 0 or avg_volume <= 0:
        return base_slippage
    
    volume_ratio = volume / avg_volume
    
    # 낮은 거래량 = 높은 슬리피지
    if volume_ratio < 0.5:
        return base_slippage * (1.5 - volume_ratio)
    # 높은 거래량 = 낮은 슬리피지
    elif volume_ratio > 2.0:
        return base_slippage * 0.8
    else:
        return base_slippage

# 가격 변동성에 따른 슬리피지 조정
def adjust_slippage_by_volatility(base_slippage, recent_volatility):
    """최근 가격 변동성에 따라 슬리피지 조정"""
    if recent_volatility <= 0:
        return base_slippage
    
    # 변동성이 매우 낮음
    if recent_volatility < 0.005:  # 0.5% 미만
        return base_slippage * 0.8
    # 변동성이 보통
    elif recent_volatility < 0.02:  # 0.5% ~ 2%
        return base_slippage
    # 변동성이 높음
    elif recent_volatility < 0.05:  # 2% ~ 5%
        return base_slippage * 1.5
    # 변동성이 매우 높음
    else:  # 5% 이상
        return base_slippage * 2.0

# 동적 수수료 계산 (거래량에 따른 티어 구조)
def calculate_dynamic_fee(exchange_id, trade_volume, position_type="taker"):
    """거래소 및 거래량에 따른 동적 수수료 계산"""
    base_fee = EXCHANGE_FEES.get(exchange_id, {}).get(position_type, 0.001)
    
    # Binance 티어 구조 (예시)
    if exchange_id in ["binance", "binanceus"]:
        if trade_volume > 1000000:  # 100만 달러 이상
            discount = 0.2  # 20% 할인
        elif trade_volume > 500000:  # 50만 달러 이상
            discount = 0.1  # 10% 할인
        elif trade_volume > 100000:  # 10만 달러 이상
            discount = 0.05  # 5% 할인
        else:
            discount = 0.0
            
        return base_fee * (1 - discount)
    
    # Upbit 티어 구조 (예시)
    elif exchange_id == "upbit":
        if trade_volume > 1000000:  # 10억 원 이상 (약 100만 달러)
            discount = 0.4  # 40% 할인
        elif trade_volume > 100000:  # 1억 원 이상 (약 10만 달러)
            discount = 0.2  # 20% 할인
        else:
            discount = 0.0
            
        return base_fee * (1 - discount)
    
    # 기타 거래소는 기본 수수료 사용
    return base_fee

# 동적 슬리피지 계산 (시장 상황에 따른 조정)
def calculate_dynamic_slippage(exchange_id, symbol, df, current_index):
    """시장 상황에 따른 동적 슬리피지 계산"""
    base_slippage = EXCHANGE_SLIPPAGE.get(exchange_id, 0.001)
    
    # 코인 기본 변동성 계수 적용
    coin_symbol = symbol.split('/')[0]
    volatility_factor = COIN_VOLATILITY.get(coin_symbol, 1.0)
    adjusted_slippage = base_slippage * volatility_factor
    
    # 현재 거래량과 최근 10개 캔들의 평균 거래량 비교
    if len(df) > 10 and current_index > 10:
        recent_candles = df.iloc[current_index-10:current_index]
        avg_volume = recent_candles['volume'].mean()
        current_volume = df.iloc[current_index]['volume'] if current_index < len(df) else avg_volume
        
        # 거래량 기반 슬리피지 조정
        adjusted_slippage = adjust_slippage_by_volume(adjusted_slippage, current_volume, avg_volume)
        
        # 최근 변동성 계산 (표준편차 / 평균 종가)
        recent_volatility = recent_candles['close'].std() / recent_candles['close'].mean()
        
        # 변동성 기반 슬리피지 조정
        adjusted_slippage = adjust_slippage_by_volatility(adjusted_slippage, recent_volatility)
    
    return adjusted_slippage

# 거래 비용 분석을 위한 함수
def analyze_transaction_costs(trades):
    """거래 기록에서 비용 분석"""
    if len(trades) == 0:
        return {
            "total_fees": 0,
            "total_slippage_cost": 0,
            "avg_fee_percent": 0,
            "avg_slippage_percent": 0,
            "total_cost_percent": 0
        }
    
    # 총 거래 금액
    total_trade_value = trades['value'].sum()
    
    # 총 수수료
    total_fees = trades['fee'].sum()
    
    # 총 슬리피지 비용
    slippage_costs = []
    for i, row in trades.iterrows():
        if row['type'] == 'BUY':
            # 매수 시 슬리피지: (실제가격 - 이론가격) * 수량
            slippage_cost = (row['effective_price'] - row['price']) * row['units']
        else:  # SELL
            # 매도 시 슬리피지: (이론가격 - 실제가격) * 수량
            slippage_cost = (row['price'] - row['effective_price']) * row['units']
        slippage_costs.append(slippage_cost)
    
    total_slippage_cost = sum(slippage_costs)
    
    # 평균 비용 비율
    avg_fee_percent = (total_fees / total_trade_value * 100) if total_trade_value > 0 else 0
    avg_slippage_percent = (total_slippage_cost / total_trade_value * 100) if total_trade_value > 0 else 0
    total_cost_percent = avg_fee_percent + avg_slippage_percent
    
    return {
        "total_fees": total_fees,
        "total_slippage_cost": total_slippage_cost,
        "avg_fee_percent": avg_fee_percent,
        "avg_slippage_percent": avg_slippage_percent,
        "total_cost_percent": total_cost_percent
    }

# 사이드바: 거래소 설정
st.sidebar.header("거래소 설정")
selected_exchange_name = st.sidebar.selectbox(
    "거래소 선택",
    list(SUPPORTED_EXCHANGES.keys())
)
exchange_id = SUPPORTED_EXCHANGES[selected_exchange_name]

# 거래소 설정 및 에러 처리
@st.cache_data(ttl=3600)
def get_exchange(exchange_id):
    try:
        exchange_class = getattr(ccxt, exchange_id)
        exchange = exchange_class({
            'enableRateLimit': True,
        })
        
        # 테스트 API 호출로 연결 확인
        exchange.load_markets()
        return {
            "exchange": exchange,
            "status": "success",
            "message": f"{exchange_id} 거래소에 연결되었습니다."
        }
    except Exception as e:
        return {
            "exchange": None,
            "status": "error",
            "message": f"{exchange_id} 연결 실패: {str(e)}"
        }

# 선택한 거래소 초기화
exchange_result = get_exchange(exchange_id)

if exchange_result["status"] == "success":
    st.sidebar.success(exchange_result["message"])
    exchange = exchange_result["exchange"]
else:
    st.sidebar.error(exchange_result["message"])
    
    # 대체 거래소 자동 시도
    st.sidebar.warning("다른 거래소로 연결을 시도합니다...")
    
    for backup_id in SUPPORTED_EXCHANGES.values():
        if backup_id != exchange_id:
            backup_result = get_exchange(backup_id)
            if backup_result["status"] == "success":
                st.sidebar.success(f"대체 거래소: {backup_result['message']}")
                exchange = backup_result["exchange"]
                exchange_id = backup_id
                # 선택된 거래소명 업데이트
                for name, id in SUPPORTED_EXCHANGES.items():
                    if id == exchange_id:
                        selected_exchange_name = name
                break
    
    if exchange_result["status"] == "error" and "exchange" not in locals():
        st.error("모든 거래소 연결에 실패했습니다. 네트워크 연결을 확인하세요.")
        st.stop()

# 거래소 수수료 정보 표시
st.sidebar.info(f"기본 수수료: Maker {EXCHANGE_FEES[exchange_id]['maker']*100:.3f}%, Taker {EXCHANGE_FEES[exchange_id]['taker']*100:.3f}%")

# 사이드바: 기본 설정
st.sidebar.header("백테스팅 설정")

# 코인 선택 - 선택된 거래소에 따라 목록 변경
symbol = st.sidebar.selectbox(
    "코인 선택",
    EXCHANGE_COINS.get(exchange_id, ["BTC/USDT", "ETH/USDT"])
)

# 시간 프레임 선택
timeframe = st.sidebar.selectbox(
    "시간 프레임",
    ["1h", "4h", "1d"]
)

# 전략 선택
strategy = st.sidebar.selectbox(
    "트레이딩 전략",
    ["MA 교차", "RSI", "볼린저 밴드"]
)

# 기간 설정
days_back = st.sidebar.slider("백테스팅 기간 (일)", 30, 365, 180)

# 초기 자본 설정
initial_capital = st.sidebar.number_input("초기 자본 (USDT)", min_value=100, value=1000)

# 수수료 설정 확장 섹션
with st.sidebar.expander("고급 수수료 설정"):
    # 수수료 설정 옵션
    fee_option = st.radio(
        "수수료 설정 방식",
        ["자동 (거래소 기본)", "수동 설정", "동적 수수료 (거래량 기반)"]
    )
    
    if fee_option == "수동 설정":
        maker_fee = st.number_input("Maker 수수료 (%)", min_value=0.0, max_value=1.0, value=float(EXCHANGE_FEES[exchange_id]['maker']*100), step=0.01) / 100
        taker_fee = st.number_input("Taker 수수료 (%)", min_value=0.0, max_value=1.0, value=float(EXCHANGE_FEES[exchange_id]['taker']*100), step=0.01) / 100
    elif fee_option == "자동 (거래소 기본)":
        maker_fee = EXCHANGE_FEES[exchange_id]['maker']
        taker_fee = EXCHANGE_FEES[exchange_id]['taker']
        st.info(f"현재 거래소의 기본 수수료를 사용합니다. (Maker: {maker_fee*100:.2f}%, Taker: {taker_fee*100:.2f}%)")
    else:  # 동적 수수료
        st.info("누적 거래량에 따라 수수료가 자동으로 조정됩니다. 거래량이 많을수록 수수료가 할인됩니다.")
        maker_fee = taker_fee = None  # 백테스팅 과정에서 동적으로 계산

# 슬리피지 설정 확장 섹션
with st.sidebar.expander("고급 슬리피지 설정"):
    # 슬리피지 설정 옵션
    slippage_option = st.radio(
        "슬리피지 설정 방식",
        ["자동 (거래소 기본)", "수동 설정", "동적 슬리피지 (시장 상황 기반)"]
    )
    
    if slippage_option == "수동 설정":
        slippage_percent = st.number_input("슬리피지 (%)", min_value=0.0, max_value=2.0, value=float(EXCHANGE_SLIPPAGE[exchange_id]*100), step=0.01) / 100
        slippage_ratio = slippage_percent
    elif slippage_option == "자동 (거래소 기본)":
        base_slippage = EXCHANGE_SLIPPAGE[exchange_id]
        coin_symbol = symbol.split('/')[0]
        volatility_factor = COIN_VOLATILITY.get(coin_symbol, 1.0)
        slippage_ratio = base_slippage * volatility_factor
        st.info(f"기본 슬리피지: {base_slippage*100:.2f}% × 코인 변동성 계수({volatility_factor:.1f}) = {slippage_ratio*100:.2f}%")
    else:  # 동적 슬리피지
        st.info("거래량과 시장 변동성에 따라 슬리피지가 자동으로 조정됩니다.")
        slippage_ratio = None  # 백테스팅 과정에서 동적으로 계산

# 위험 관리 설정 (손절매/이익실현)
st.sidebar.header("위험 관리 설정")
enable_stoploss = st.sidebar.checkbox("손절매(Stop Loss) 활성화", value=False)
if enable_stoploss:
    stoploss_percent = st.sidebar.slider("손절매 비율 (%)", min_value=1.0, max_value=15.0, value=5.0, step=0.5) / 100

enable_takeprofit = st.sidebar.checkbox("이익실현(Take Profit) 활성화", value=False)
if enable_takeprofit:
    takeprofit_percent = st.sidebar.slider("이익실현 비율 (%)", min_value=1.0, max_value=20.0, value=10.0, step=0.5) / 100

enable_trailing_stop = st.sidebar.checkbox("트레일링 스탑 활성화", value=False)
if enable_trailing_stop:
    trailing_stop_percent = st.sidebar.slider("트레일링 스탑 비율 (%)", min_value=1.0, max_value=15.0, value=5.0, step=0.5) / 100

# OHLCV 데이터 가져오기
@st.cache_data(ttl=3600)
def fetch_ohlcv(_exchange, symbol, timeframe, since, limit=1000):
    cache_file = f"cache/{_exchange.id}_{symbol.replace('/', '_')}_{timeframe}_{since}.csv"
    
    # 캐시 파일이 존재하면 로드
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)
    
    try:
        # 데이터 가져오기
        ohlcv = _exchange.fetch_ohlcv(symbol, timeframe, since, limit)
        
        # 데이터프레임 변환
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        # 캐시 저장
        df.to_csv(cache_file)
        
        return df
    except Exception as e:
        st.error(f"데이터를 가져오는 데 실패했습니다: {str(e)}")
        # 샘플 데이터 생성 (대체 데이터)
        st.warning("샘플 데이터를 사용합니다.")
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        date_range = pd.date_range(start=start_date, end=end_date, freq='D')
        
        # 랜덤 가격 생성
        np.random.seed(42)  # 재현성을 위한 시드 설정
        base_price = 100
        prices = [base_price]
        for i in range(1, len(date_range)):
            change = np.random.normal(0, 2)  # 평균 0, 표준편차 2의 정규분포
            new_price = max(prices[-1] * (1 + change/100), 1)  # 최소 가격은 1
            prices.append(new_price)
        
        # 캔들스틱 데이터 생성
        df = pd.DataFrame(index=date_range)
        df['close'] = prices
        df['open'] = df['close'].shift(1).fillna(df['close'][0] * 0.99)
        df['high'] = df[['open', 'close']].max(axis=1) * (1 + np.random.uniform(0, 0.03, len(df)))
        df['low'] = df[['open', 'close']].min(axis=1) * (1 - np.random.uniform(0, 0.03, len(df)))
        df['volume'] = np.random.uniform(1000, 10000, len(df))
        
        return df

# 전략 구현 - MA 교차
def ma_cross_strategy(df, short_window=20, long_window=50):
    signals = pd.DataFrame(index=df.index)
    signals['price'] = df['close']
    signals['short_ma'] = df['close'].rolling(window=short_window, min_periods=1).mean()
    signals['long_ma'] = df['close'].rolling(window=long_window, min_periods=1).mean()
    
    # 매수 신호: 단기 MA가 장기 MA를 상향 돌파
    signals['signal'] = 0
    signals['signal'][short_window:] = np.where(
        signals['short_ma'][short_window:] > signals['long_ma'][short_window:], 1, 0
    )
    
    # 포지션 변화 감지
    signals['position'] = signals['signal'].diff()
    
    return signals

# 전략 구현 - RSI
def rsi_strategy(df, rsi_period=14, oversold=30, overbought=70):
    signals = pd.DataFrame(index=df.index)
    signals['price'] = df['close']
    
    # RSI 계산
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    signals['rsi'] = rsi
    
    # 매수 신호: RSI가 oversold 아래로 갔다가 다시 올라옴
    # 매도 신호: RSI가 overbought 위로 갔다가 다시 내려옴
    signals['signal'] = 0
    signals['signal'] = np.where(signals['rsi'] < oversold, 1, 0)  # 매수
    signals['signal'] = np.where(signals['rsi'] > overbought, 0, signals['signal'])  # 매도
    
    # 포지션 변화 감지
    signals['position'] = signals['signal'].diff()
    
    return signals

# 전략 구현 - 볼린저 밴드
def bollinger_bands_strategy(df, window=20, num_std=2):
    signals = pd.DataFrame(index=df.index)
    signals['price'] = df['close']
    
    # 볼린저 밴드 계산
    signals['rolling_mean'] = df['close'].rolling(window=window).mean()
    signals['rolling_std'] = df['close'].rolling(window=window).std()
    signals['upper_band'] = signals['rolling_mean'] + (signals['rolling_std'] * num_std)
    signals['lower_band'] = signals['rolling_mean'] - (signals['rolling_std'] * num_std)
    
    # 매수 신호: 가격이 하단 밴드 아래로 갔다가 다시 위로
    # 매도 신호: 가격이 상단 밴드 위로 갔다가 다시 아래로
    signals['signal'] = 0
    signals['signal'] = np.where(signals['price'] < signals['lower_band'], 1, 0)  # 매수
    signals['signal'] = np.where(signals['price'] > signals['upper_band'], 0, signals['signal'])  # 매도
    
    # 포지션 변화 감지
    signals['position'] = signals['signal'].diff()
    
    return signals

# 백테스팅 함수 (고급 수수료, 슬리피지 및 위험 관리 포함)
def backtest(df, signals, initial_capital=1000.0, 
             maker_fee=None, taker_fee=None, 
             slippage_ratio=None, 
             enable_stoploss=False, stoploss_percent=0.05,
             enable_takeprofit=False, takeprofit_percent=0.1,
             enable_trailing_stop=False, trailing_stop_percent=0.05,
             exchange_id=None, symbol=None):
    
    positions = pd.DataFrame(index=signals.index).fillna(0.0)
    positions['asset'] = signals['signal']  # 보유 자산 (0 또는 1)
    
    # 포트폴리오 가치 계산
    portfolio = pd.DataFrame(index=signals.index)
    portfolio['positions'] = positions['asset'] * signals['price']  # 보유 자산 가치
    
    # 현금 및 총 가치 계산 (수수료 및 슬리피지 포함)
    cash = initial_capital
    total_values = []
    cumulative_trade_volume = 0  # 누적 거래량 (동적 수수료 계산용)
    
    # 위험 관리 변수
    in_position = False
    entry_price = 0
    highest_price = 0  # 트레일링 스탑용
    
    # 거래 기록
    trades = pd.DataFrame(columns=['timestamp', 'type', 'price', 'effective_price', 'units', 'value', 'fee', 'reason'])
    
    for i, row in signals.iterrows():
        current_price = row['price']
        current_index = df.index.get_loc(i)
        
        # 동적 수수료 및 슬리피지 계산
        if maker_fee is None or taker_fee is None:
            current_maker_fee = calculate_dynamic_fee(exchange_id, cumulative_trade_volume, "maker")
            current_taker_fee = calculate_dynamic_fee(exchange_id, cumulative_trade_volume, "taker")
        else:
            current_maker_fee = maker_fee
            current_taker_fee = taker_fee
            
        if slippage_ratio is None:
            current_slippage = calculate_dynamic_slippage(exchange_id, symbol, df, current_index)
        else:
            current_slippage = slippage_ratio
        
        # 거래 신호 처리 전에 위험 관리 조건 체크
        if in_position:
            # 이익실현 조건 체크
            if enable_takeprofit and current_price >= entry_price * (1 + takeprofit_percent):
                # 이익실현 매도 실행
                effective_price = current_price * (1 - current_slippage)
                position_value = portfolio.loc[i, 'positions'] if i in portfolio.index else 0
                units = position_value / current_price
                fee = effective_price * units * current_taker_fee
                
                trade = {
                    'timestamp': i,
                    'type': 'SELL',
                    'price': current_price,
                    'effective_price': effective_price,
                    'units': units,
                    'value': units * effective_price,
                    'fee': fee,
                    'reason': 'TAKE_PROFIT'
                }
                trades = pd.concat([trades, pd.DataFrame([trade])], ignore_index=True)
                
                # 포지션 업데이트
                positions.loc[i, 'asset'] = 0
                in_position = False
                cash = units * effective_price - fee
                cumulative_trade_volume += units * effective_price
                
            # 손절매 조건 체크
            elif enable_stoploss and current_price <= entry_price * (1 - stoploss_percent):
                # 손절매 매도 실행
                effective_price = current_price * (1 - current_slippage)
                position_value = portfolio.loc[i, 'positions'] if i in portfolio.index else 0
                units = position_value / current_price
                fee = effective_price * units * current_taker_fee
                
                trade = {
                    'timestamp': i,
                    'type': 'SELL',
                    'price': current_price,
                    'effective_price': effective_price,
                    'units': units,
                    'value': units * effective_price,
                    'fee': fee,
                    'reason': 'STOP_LOSS'
                }
                trades = pd.concat([trades, pd.DataFrame([trade])], ignore_index=True)
                
                # 포지션 업데이트
                positions.loc[i, 'asset'] = 0
                in_position = False
                cash = units * effective_price - fee
                cumulative_trade_volume += units * effective_price
                
            # 트레일링 스탑 조건 체크
            elif enable_trailing_stop:
                # 최고가 업데이트
                if current_price > highest_price:
                    highest_price = current_price
                
                # 최고가에서 하락폭이 트레일링 스탑 비율을 초과하면 매도
                if current_price <= highest_price * (1 - trailing_stop_percent):
                    # 트레일링 스탑 매도 실행
                    effective_price = current_price * (1 - current_slippage)
                    position_value = portfolio.loc[i, 'positions'] if i in portfolio.index else 0
                    units = position_value / current_price
                    fee = effective_price * units * current_taker_fee
                    
                    trade = {
                        'timestamp': i,
                        'type': 'SELL',
                        'price': current_price,
                        'effective_price': effective_price,
                        'units': units,
                        'value': units * effective_price,
                        'fee': fee,
                        'reason': 'TRAILING_STOP'
                    }
                    trades = pd.concat([trades, pd.DataFrame([trade])], ignore_index=True)
                    
                    # 포지션 업데이트
                    positions.loc[i, 'asset'] = 0
                    in_position = False
                    cash = units * effective_price - fee
                    cumulative_trade_volume += units * effective_price
        
        # 매수 또는 매도 시 수수료 및 슬리피지 계산
        position_change = positions['asset'].diff().fillna(0).loc[i]
        
        # 전략 기반 매수/매도 신호 처리 (위험 관리 규칙 적용 후)
        if position_change > 0 and not in_position:  # 매수
            # 슬리피지 적용 가격
            effective_price = current_price * (1 + current_slippage)
            # 수수료 계산
            fee = cash * current_taker_fee
            # 구매할 수 있는 자산 수량
            asset_amount = (cash - fee) / effective_price
            cash = 0  # 모든 현금을 자산 구매에 사용
            
            # 거래 기록 추가
            trade = {
                'timestamp': i,
                'type': 'BUY',
                'price': current_price,
                'effective_price': effective_price,
                'units': asset_amount,
                'value': asset_amount * current_price,
                'fee': fee,
                'reason': 'SIGNAL'
            }
            trades = pd.concat([trades, pd.DataFrame([trade])], ignore_index=True)
            
            # 매수 후 상태 업데이트
            in_position = True
            entry_price = effective_price
            highest_price = current_price  # 트레일링 스탑 기준 설정
            cumulative_trade_volume += asset_amount * current_price
            
            position_value = asset_amount * current_price
            total_value = position_value + cash
            
        elif position_change < 0 and in_position:  # 매도
            # 슬리피지 적용 가격
            effective_price = current_price * (1 - current_slippage)
            # 보유 자산 가치
            position_value = portfolio.loc[i, 'positions'] if i in portfolio.index else 0
            # 매도할 자산 수량
            units = position_value / current_price
            # 매도 후 현금 (수수료 차감)
            fee = effective_price * units * current_taker_fee
            cash = units * effective_price - fee
            
            # 거래 기록 추가
            trade = {
                'timestamp': i,
                'type': 'SELL',
                'price': current_price,
                'effective_price': effective_price,
                'units': units,
                'value': units * effective_price,
                'fee': fee,
                'reason': 'SIGNAL'
            }
            trades = pd.concat([trades, pd.DataFrame([trade])], ignore_index=True)
            
            # 매도 후 상태 업데이트
            in_position = False
            entry_price = 0
            highest_price = 0
            cumulative_trade_volume += units * effective_price
            
            position_value = 0
            total_value = cash
            
        else:  # 포지션 변화 없음
            if positions['asset'].loc[i] == 1:  # 자산 보유 중
                position_value = portfolio.loc[i, 'positions'] if i in portfolio.index else 0
                total_value = position_value + cash
            else:  # 현금 보유 중
                position_value = 0
                total_value = cash
        
        total_values.append(total_value)
    
    # 포트폴리오 정보 업데이트
    portfolio['cash'] = pd.Series(initial_capital, index=signals.index)
    for i, trade in trades.iterrows():
        if trade['type'] == 'BUY':
            # 매수 시 현금 감소
            portfolio.loc[trade['timestamp']:, 'cash'] -= (trade['value'] + trade['fee'])
        else:  # SELL
            # 매도 시 현금 증가
            portfolio.loc[trade['timestamp']:, 'cash'] += (trade['value'] - trade['fee'])
    
    portfolio['total'] = pd.Series(total_values, index=signals.index)
    portfolio['returns'] = portfolio['total'].pct_change()
    
    return portfolio, trades

# 전략 파라미터 사이드바 추가
if strategy == "MA 교차":
    st.sidebar.subheader("MA 교차 파라미터")
    short_window = st.sidebar.slider("단기 이동평균 기간", 5, 50, 20)
    long_window = st.sidebar.slider("장기 이동평균 기간", 20, 200, 50)
    
elif strategy == "RSI":
    st.sidebar.subheader("RSI 파라미터")
    rsi_period = st.sidebar.slider("RSI 기간", 5, 30, 14)
    oversold = st.sidebar.slider("과매도 기준", 20, 40, 30)
    overbought = st.sidebar.slider("과매수 기준", 60, 80, 70)
    
elif strategy == "볼린저 밴드":
    st.sidebar.subheader("볼린저 밴드 파라미터")
    bb_window = st.sidebar.slider("이동평균 기간", 5, 50, 20)
    bb_std = st.sidebar.slider("표준편차 배수", 1.0, 3.0, 2.0, 0.1)

# 백테스팅 시작 버튼
start_backtest = st.sidebar.button("백테스팅 시작")

# 초기 안내 메시지
if not start_backtest:
    st.info("👈 왼쪽 사이드바에서 백테스팅 설정 후 '백테스팅 시작' 버튼을 클릭하세요.")
    
    # 사용 안내
    st.subheader("사용 방법")
    st.markdown("""
    1. **거래소 선택**: 데이터를 가져올 거래소를 선택합니다.
    2. **코인 선택**: 백테스팅할 코인을 선택합니다.
    3. **시간 프레임**: 분석할 시간 단위를 선택합니다.
    4. **트레이딩 전략**: 백테스팅에 사용할 전략을 선택합니다.
    5. **백테스팅 기간**: 과거 몇 일 동안의 데이터로 백테스팅할지 설정합니다.
    6. **초기 자본**: 백테스팅 시작 자본을 설정합니다.
    7. **위험 관리 설정**: 손절매, 이익실현, 트레일링 스탑 조건을 설정합니다.
    8. **수수료 및 슬리피지**: 실제 거래 환경을 시뮬레이션하기 위한 설정입니다.
    9. **전략 파라미터**: 선택한 전략에 맞는 파라미터를 조정합니다.
    10. **백테스팅 시작** 버튼을 클릭하여 결과를 확인합니다.
    """)
    
    # 전략 설명
    st.subheader("지원하는 전략")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("#### MA 교차 전략")
        st.markdown("""
        단기 이동평균선이 장기 이동평균선을 상향 돌파할 때 매수하고, 
        하향 돌파할 때 매도하는 전략입니다.
        """)
    
    with col2:
        st.markdown("#### RSI 전략")
        st.markdown("""
        RSI가 과매도 수준(기본값 30) 아래로 갔다가 다시 올라옴
        과매수 수준(기본값 70) 위로 올라갈 때 매도하는 전략입니다.
        """)
    
    with col3:
        st.markdown("#### 볼린저 밴드 전략")
        st.markdown("""
        가격이 하단 밴드 아래로 내려갈 때 매수하고, 
        상단 밴드 위로 올라갈 때 매도하는 전략입니다.
        """)
    
    # 위험 관리 설명
    st.subheader("위험 관리 기능")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("#### 손절매(Stop Loss)")
        st.markdown("""
        진입 가격에서 설정한 비율만큼 가격이 하락하면 자동으로 매도합니다.
        손실을 제한하여 위험을 관리하는 기능입니다.
        """)
    
    with col2:
        st.markdown("#### 이익실현(Take Profit)")
        st.markdown("""
        진입 가격에서 설정한 비율만큼 가격이 상승하면 자동으로 매도합니다.
        목표 수익에 도달했을 때 이익을 확정하는 기능입니다.
        """)
    
    with col3:
        st.markdown("#### 트레일링 스탑(Trailing Stop)")
        st.markdown("""
        가격이 계속 상승할 때 손절매 수준도 함께 올라갑니다.
        최고 가격에서 설정한 비율만큼 하락하면 매도하는 기능입니다.
        """)

if start_backtest:
    with st.spinner('데이터 로딩 중...'):
        # 종료 날짜: 현재
        end_date = datetime.now()
        # 시작 날짜: 종료 날짜에서 days_back일 전
        start_date = end_date - timedelta(days=days_back)
        
        # UNIX 타임스탬프로 변환 (밀리초 단위)
        since = int(start_date.timestamp() * 1000)
        
        # 데이터 가져오기
        try:
            df = fetch_ohlcv(exchange, symbol, timeframe, since)
            
            # 선택한 전략 적용
            if strategy == "MA 교차":
                signals = ma_cross_strategy(df, short_window, long_window)
                strategy_params = f"단기: {short_window}, 장기: {long_window}"
            elif strategy == "RSI":
                signals = rsi_strategy(df, rsi_period, oversold, overbought)
                strategy_params = f"기간: {rsi_period}, 과매도: {oversold}, 과매수: {overbought}"
            else:  # 볼린저 밴드
                signals = bollinger_bands_strategy(df, bb_window, bb_std)
                strategy_params = f"기간: {bb_window}, 표준편차: {bb_std}"
            
            # 수수료 설정 확인
            if fee_option == "수동 설정":
                current_maker_fee = maker_fee
                current_taker_fee = taker_fee
            elif fee_option == "자동 (거래소 기본)":
                current_maker_fee = EXCHANGE_FEES[exchange_id]['maker']
                current_taker_fee = EXCHANGE_FEES[exchange_id]['taker']
            else:  # 동적 수수료
                current_maker_fee = None
                current_taker_fee = None
            
            # 슬리피지 설정 확인
            current_slippage = slippage_ratio  # 이미 설정된 slippage_ratio 사용
            
            # 백테스팅 실행 (고급 수수료, 슬리피지 및 위험 관리 포함)
            portfolio, trades = backtest(df, signals, initial_capital, 
                                         maker_fee=current_maker_fee, taker_fee=current_taker_fee,
                                         slippage_ratio=current_slippage,
                                         enable_stoploss=enable_stoploss, stoploss_percent=stoploss_percent if enable_stoploss else 0,
                                         enable_takeprofit=enable_takeprofit, takeprofit_percent=takeprofit_percent if enable_takeprofit else 0,
                                         enable_trailing_stop=enable_trailing_stop, trailing_stop_percent=trailing_stop_percent if enable_trailing_stop else 0,
                                         exchange_id=exchange_id, symbol=symbol)
            
            # 성과 지표 계산
            total_return = ((portfolio['total'].iloc[-1] / initial_capital) - 1) * 100
            max_drawdown = (portfolio['total'] / portfolio['total'].cummax() - 1).min() * 100
            
            # 승률 계산
            if len(trades) > 0:
                # 거래 쌍 계산 (매수-매도)
                trades['profit'] = 0
                
                # 각 매수 후 매도까지의 순이익 계산
                buy_trades = trades[trades['type'] == 'BUY']
                sell_trades = trades[trades['type'] == 'SELL']
                
                # 매수-매도 쌍이 같은 수인지 확인
                if len(buy_trades) > 0:
                    # 마지막 매수가 매도 없이 끝난 경우 처리
                    if len(buy_trades) > len(sell_trades):
                        # 마지막 포지션 정리 (마지막 가격으로 가상 매도)
                        last_buy = buy_trades.iloc[-1]
                        last_price = df['close'].iloc[-1]
                        
                        # 가상 매도 거래 추가
                        virtual_sell = last_buy.copy()
                        virtual_sell['type'] = 'SELL'
                        virtual_sell['price'] = last_price
                        virtual_sell['effective_price'] = last_price
                        virtual_sell['timestamp'] = df.index[-1]
                        virtual_sell['reason'] = 'END_OF_PERIOD'
                        
                        sell_trades = pd.concat([sell_trades, pd.DataFrame([virtual_sell])], ignore_index=True)
                
                # 각 매수-매도 쌍에 대한 이익 계산
                for i in range(min(len(buy_trades), len(sell_trades))):
                    buy = buy_trades.iloc[i]
                    sell = sell_trades.iloc[i]
                    
                    # 수수료를 고려한 순이익
                    buy_cost = buy['value'] + buy['fee']
                    sell_revenue = sell['value'] - sell['fee']
                    profit = sell_revenue - buy_cost
                    
                    # 매도 거래에 이익 정보 추가
                    trades.loc[trades['timestamp'] == sell['timestamp'], 'profit'] = profit
                
                # 승률 계산
                wins = len(trades[trades['profit'] > 0])
                total_trades = len(trades[trades['profit'] != 0])
                win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
            else:
                win_rate = 0
            
            # 거래 비용 분석
            cost_analysis = analyze_transaction_costs(trades)
                
            # 결과 표시
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("총 수익률", f"{total_return:.2f}%")
            col2.metric("최대 손실폭 (MDD)", f"{max_drawdown:.2f}%")
            col3.metric("승률", f"{win_rate:.2f}%")
            col4.metric("거래 횟수", f"{len(trades[trades['type'] == 'BUY'].index)}")
            
            # 거래 비용 표시
            st.subheader("거래 비용 분석")
            cost_col1, cost_col2, cost_col3, cost_col4 = st.columns(4)
            cost_col1.metric("총 수수료", f"{cost_analysis['total_fees']:.2f} {symbol.split('/')[1]}")
            cost_col2.metric("총 슬리피지 비용", f"{cost_analysis['total_slippage_cost']:.2f} {symbol.split('/')[1]}")
            cost_col3.metric("평균 수수료 비율", f"{cost_analysis['avg_fee_percent']:.2f}%")
            cost_col4.metric("평균 슬리피지 비율", f"{cost_analysis['avg_slippage_percent']:.2f}%")
            
            # 차트 생성
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                               vertical_spacing=0.03, 
                               subplot_titles=(f'{symbol} 가격 및 신호', '포트폴리오 가치'),
                               row_heights=[0.7, 0.3])
            
            # 가격 차트
            fig.add_trace(
                go.Candlestick(x=df.index,
                    open=df['open'],
                    high=df['high'],
                    low=df['low'],
                    close=df['close'],
                    name='가격'),
                row=1, col=1
            )
            
            # 전략별 지표 추가
            if strategy == "MA 교차":
                fig.add_trace(
                    go.Scatter(x=signals.index, y=signals['short_ma'], name=f'{short_window}일 MA', line=dict(color='blue')),
                    row=1, col=1
                )
                fig.add_trace(
                    go.Scatter(x=signals.index, y=signals['long_ma'], name=f'{long_window}일 MA', line=dict(color='orange')),
                    row=1, col=1
                )
            elif strategy == "RSI":
                # RSI 추가 차트
                fig2 = make_subplots(rows=3, cols=1, shared_xaxes=True,
                                    vertical_spacing=0.03,
                                    subplot_titles=(f'{symbol} 가격 및 신호', 'RSI', '포트폴리오 가치'),
                                    row_heights=[0.5, 0.2, 0.3])
                
                # 가격 차트 (fig2)
                fig2.add_trace(
                    go.Candlestick(x=df.index,
                        open=df['open'],
                        high=df['high'],
                        low=df['low'],
                        close=df['close'],
                        name='가격'),
                    row=1, col=1
                )
                
                # RSI 차트 추가 (fig2)
                fig2.add_trace(
                    go.Scatter(x=signals.index, y=signals['rsi'], name='RSI', line=dict(color='purple')),
                    row=2, col=1
                )
                # 과매수/과매도 선 추가 (fig2)
                fig2.add_hline(y=oversold, line_width=1, line_dash="dash", line_color="green", row=2, col=1)
                fig2.add_hline(y=overbought, line_width=1, line_dash="dash", line_color="red", row=2, col=1)
                
                # 포트폴리오 가치 차트 (fig2)
                fig2.add_trace(
                    go.Scatter(x=portfolio.index, y=portfolio['total'], name='포트폴리오 가치', line=dict(color='green')),
                    row=3, col=1
                )
                
                # 원래 차트에도 RSI 관련 지표 추가
                fig.add_trace(
                    go.Scatter(x=signals.index, y=signals['rsi'], name='RSI', line=dict(color='purple')),
                    row=1, col=1
                )
            else:  # 볼린저 밴드
                fig.add_trace(
                    go.Scatter(x=signals.index, y=signals['rolling_mean'], name='MA', line=dict(color='blue')),
                    row=1, col=1
                )
                fig.add_trace(
                    go.Scatter(x=signals.index, y=signals['upper_band'], name='상단 밴드', line=dict(color='red')),
                    row=1, col=1
                )
                fig.add_trace(
                    go.Scatter(x=signals.index, y=signals['lower_band'], name='하단 밴드', line=dict(color='green')),
                    row=1, col=1
                )
            
            # 거래 신호 표시
            buy_trades = trades[trades['type'] == 'BUY']
            sell_trades = trades[trades['type'] == 'SELL']
            
            # 거래 이유에 따른 색상 설정
            buy_colors = {
                'SIGNAL': 'green',
                'END_OF_PERIOD': 'grey'
            }
            
            sell_colors = {
                'SIGNAL': 'red',
                'STOP_LOSS': 'darkred',
                'TAKE_PROFIT': 'purple',
                'TRAILING_STOP': 'orange',
                'END_OF_PERIOD': 'grey'
            }
            
            # 매수 신호 표시 (거래 이유별로 분리)
            for reason in buy_trades['reason'].unique():
                reason_buys = buy_trades[buy_trades['reason'] == reason]
                fig.add_trace(
                    go.Scatter(
                        x=reason_buys['timestamp'],
                        y=reason_buys['price'],
                        name=f'매수 ({reason})',
                        mode='markers',
                        marker=dict(
                            symbol='triangle-up',
                            size=15,
                            color=buy_colors.get(reason, 'green')
                        )
                    ),
                    row=1, col=1
                )
            
            # 매도 신호 표시 (거래 이유별로 분리)
            for reason in sell_trades['reason'].unique():
                reason_sells = sell_trades[sell_trades['reason'] == reason]
                fig.add_trace(
                    go.Scatter(
                        x=reason_sells['timestamp'],
                        y=reason_sells['price'],
                        name=f'매도 ({reason})',
                        mode='markers',
                        marker=dict(
                            symbol='triangle-down',
                            size=15,
                            color=sell_colors.get(reason, 'red')
                        )
                    ),
                    row=1, col=1
                )
            
            # RSI 전략일 경우 fig2에도 거래 신호 추가
            if strategy == "RSI":
                for reason in buy_trades['reason'].unique():
                    reason_buys = buy_trades[buy_trades['reason'] == reason]
                    fig2.add_trace(
                        go.Scatter(
                            x=reason_buys['timestamp'],
                            y=reason_buys['price'],
                            name=f'매수 ({reason})',
                            mode='markers',
                            marker=dict(
                                symbol='triangle-up',
                                size=15,
                                color=buy_colors.get(reason, 'green')
                            )
                        ),
                        row=1, col=1
                    )
                
                for reason in sell_trades['reason'].unique():
                    reason_sells = sell_trades[sell_trades['reason'] == reason]
                    fig2.add_trace(
                        go.Scatter(
                            x=reason_sells['timestamp'],
                            y=reason_sells['price'],
                            name=f'매도 ({reason})',
                            mode='markers',
                            marker=dict(
                                symbol='triangle-down',
                                size=15,
                                color=sell_colors.get(reason, 'red')
                            )
                        ),
                        row=1, col=1
                    )
            
            # 포트폴리오 가치 차트
            fig.add_trace(
                go.Scatter(x=portfolio.index, y=portfolio['total'], name='포트폴리오 가치', line=dict(color='green')),
                row=2, col=1
            )
            
            # 차트 레이아웃 설정
            fig.update_layout(
                title=f'백테스팅 결과: {symbol} - {strategy} ({strategy_params})',
                xaxis_title='날짜',
                yaxis_title='가격 ({})'.format(symbol.split('/')[1]),
                height=800,
                xaxis_rangeslider_visible=False
            )
            
            # RSI 전략일 경우 fig2 레이아웃 설정
            if strategy == "RSI":
                fig2.update_layout(
                    title=f'백테스팅 결과: {symbol} - RSI 전략 ({strategy_params})',
                    xaxis_title='날짜',
                    yaxis_title='가격 ({})'.format(symbol.split('/')[1]),
                    height=1000,
                    xaxis_rangeslider_visible=False
                )
                
                # RSI 차트 y축 범위 설정
                fig2.update_yaxes(range=[0, 100], row=2, col=1)
            
            # 차트 표시
            if strategy == "RSI":
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.plotly_chart(fig, use_container_width=True)
            
            # 거래 기록 표시
            if len(trades) > 0:
                st.subheader("거래 기록")
                
                # 표시할 열 선택
                display_cols = ['timestamp', 'type', 'reason', 'price', 'effective_price', 'units', 'value', 'fee']
                if 'profit' in trades.columns:
                    display_cols.append('profit')
                
                st.dataframe(trades[display_cols])
            
                # 거래 통계
                total_profit = trades['profit'].sum() if 'profit' in trades.columns else 0
                total_fees = trades['fee'].sum()
                
                if 'profit' in trades.columns and len(trades[trades['profit'] != 0]) > 0:
                    avg_profit = trades[trades['profit'] != 0]['profit'].mean()
                    max_profit = trades['profit'].max()
                    max_loss = trades['profit'].min()
                else:
                    avg_profit = max_profit = max_loss = 0
                
                # 거래 이유별 통계
                reason_stats = pd.DataFrame(columns=['count', 'total_profit', 'avg_profit', 'win_rate'])
                for reason in trades['reason'].unique():
                    reason_trades = trades[trades['reason'] == reason]
                    reason_sells = reason_trades[reason_trades['type'] == 'SELL']
                    
                    if len(reason_sells) > 0:
                        reason_profit = reason_sells['profit'].sum()
                        reason_avg_profit = reason_sells['profit'].mean()
                        reason_wins = len(reason_sells[reason_sells['profit'] > 0])
                        reason_win_rate = (reason_wins / len(reason_sells)) * 100 if len(reason_sells) > 0 else 0
                        
                        reason_stats = pd.concat([reason_stats, pd.DataFrame({
                            'count': [len(reason_sells)],
                            'total_profit': [reason_profit],
                            'avg_profit': [reason_avg_profit],
                            'win_rate': [reason_win_rate]
                        }, index=[reason])], axis=0)
                
                st.subheader("거래 통계")
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("총 이익/손실", f"{total_profit:.2f} {symbol.split('/')[1]}")
                col2.metric("평균 이익/손실", f"{avg_profit:.2f} {symbol.split('/')[1]}")
                col3.metric("총 수수료", f"{total_fees:.2f} {symbol.split('/')[1]}")
                
                if max_profit > 0:
                    col4.metric("최대 이익", f"{max_profit:.2f} {symbol.split('/')[1]}")
                if max_loss < 0:
                    col4.metric("최대 손실", f"{max_loss:.2f} {symbol.split('/')[1]}")
                
                # 거래 이유별 성과 표시
                if len(reason_stats) > 0:
                    st.subheader("거래 이유별 성과")
                    st.dataframe(reason_stats)
                
                # 월별 성과
                if len(portfolio) > 30:  # 최소 한 달 이상의 데이터가 있는 경우
                    st.subheader("월별 성과")
                    monthly_returns = portfolio['returns'].resample('M').sum() * 100
                    
                    fig_monthly = go.Figure()
                    fig_monthly.add_trace(
                        go.Bar(
                            x=monthly_returns.index,
                            y=monthly_returns.values,
                            marker_color=np.where(monthly_returns > 0, 'green', 'red')
                        )
                    )
                    
                    fig_monthly.update_layout(
                        title='월별 수익률 (%)',
                        xaxis_title='월',
                        yaxis_title='수익률 (%)',
                        height=400
                    )
                    
                    st.plotly_chart(fig_monthly, use_container_width=True)
                    
                # 샤프 비율 계산
                risk_free_rate = 0.02 / 365  # 연 2%의 무위험 수익률 가정 (일일)
                daily_returns = portfolio['returns'].dropna()
                
                if len(daily_returns) > 1:
                    excess_returns = daily_returns - risk_free_rate
                    sharpe_ratio = np.sqrt(252) * excess_returns.mean() / excess_returns.std() if excess_returns.std() != 0 else 0
                    
                    st.subheader("위험 조정 성과 지표")
                    col1, col2 = st.columns(2)
                    col1.metric("샤프 비율", f"{sharpe_ratio:.2f}")
                    
                    # 최대 드로다운 기간 계산
                    portfolio['dd'] = portfolio['total'] / portfolio['total'].cummax() - 1
                    max_dd = portfolio['dd'].min()
                    max_dd_idx = portfolio['dd'].idxmin()
                    
                    # 최대 드로다운 시작점 찾기
                    dd_start = portfolio['total'][:max_dd_idx].idxmax()
                    dd_end = max_dd_idx
                    dd_days = (dd_end - dd_start).days
                    
                    col2.metric("최대 드로다운 기간", f"{dd_days}일")
                    
                    # 수익률 분포 히스토그램
                    st.subheader("일일 수익률 분포")
                    fig_hist = go.Figure()
                    fig_hist.add_trace(
                        go.Histogram(
                            x=daily_returns * 100,
                            nbinsx=30,
                            marker_color='blue'
                        )
                    )
                    
                    fig_hist.update_layout(
                        title='일일 수익률 분포 (%)',
                        xaxis_title='수익률 (%)',
                        yaxis_title='빈도',
                        height=300
                    )
                    
                    st.plotly_chart(fig_hist, use_container_width=True)
            else:
                st.warning("해당 기간과 전략에서는 거래가 발생하지 않았습니다. 파라미터를 조정해보세요.")
                
        except Exception as e:
            st.error(f"오류가 발생했습니다: {str(e)}")
            st.info("다른 코인, 시간 프레임 또는 기간을 선택해보세요.")

# 앱 정보 표시
with st.expander("앱 정보"):
    st.markdown(f"""
    ### 코인 백테스팅 시스템 v1.2
    
    이 앱은 암호화폐 트레이딩 전략을 테스트하기 위한 백테스팅 도구입니다.
    
    **현재 거래소:** {selected_exchange_name}
    
    **지원 기능:**
    - 다중 거래소 지원 (Binance, Binance US, Upbit, Kraken, KuCoin)
    - 주요 기술적 분석 전략 (MA 교차, RSI, 볼린저 밴드)
    - 고급 수수료 및 슬리피지 시뮬레이션 (거래소별, 거래량별, 변동성별)
    - 위험 관리 기능 (손절매, 이익실현, 트레일링 스탑)
    - 상세한 성과 지표 및 시각화
    - 위험 조정 성과 분석 (샤프 비율 등)
    
    **새로운 기능 (v1.2):**
    - 거래소별 실제 수수료율 적용
    - 동적 수수료 및 슬리피지 계산
    - 손절매/이익실현/트레일링 스탑 지원
    - 거래 이유별 성과 분석
    - 거래 비용 분석 (수수료, 슬리피지)
    
    **사용된 라이브러리:**
    - Streamlit: 웹 인터페이스
    - CCXT: 암호화폐 거래소 API
    - Pandas/NumPy: 데이터 처리
    - Plotly: 데이터 시각화
    
    **주의사항:**
    이 시스템은 교육 및 연구 목적으로 제작되었으며, 실제 투자 결정에 사용하기 전에 철저한 검증이 필요합니다.
    과거 성과가 미래 성과를 보장하지 않습니다.
    """)