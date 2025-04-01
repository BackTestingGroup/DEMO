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

# 거래소 설정
@st.cache_data
def get_exchange():
    return ccxt.binance({
        'enableRateLimit': True,
    })

exchange = get_exchange()

# 사이드바: 설정
st.sidebar.header("백테스팅 설정")

# 코인 선택
symbol = st.sidebar.selectbox(
    "코인 선택",
    ["BTC/USDT", "ETH/USDT", "ADA/USDT", "SOL/USDT", "XRP/USDT"]
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

# OHLCV 데이터 가져오기
@st.cache_data(ttl=3600)
def fetch_ohlcv(symbol, timeframe, since, limit=1000):
    cache_file = f"cache/{symbol.replace('/', '_')}_{timeframe}_{since}.csv"
    
    # 캐시 파일이 존재하면 로드
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)
    
    # 데이터 가져오기
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since, limit)
    
    # 데이터프레임 변환
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    
    # 캐시 저장
    df.to_csv(cache_file)
    
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

# 백테스팅 함수
def backtest(signals, initial_capital=1000.0):
    positions = pd.DataFrame(index=signals.index).fillna(0.0)
    positions['asset'] = signals['signal']  # 보유 자산 (0 또는 1)
    
    # 포트폴리오 가치 계산
    portfolio = pd.DataFrame(index=signals.index)
    portfolio['positions'] = positions['asset'] * signals['price']  # 보유 자산 가치
    portfolio['cash'] = initial_capital - (positions['asset'].diff().fillna(0) * signals['price']).cumsum()  # 현금
    portfolio['total'] = portfolio['positions'] + portfolio['cash']  # 총 가치
    portfolio['returns'] = portfolio['total'].pct_change()  # 수익률
    
    # 거래 기록
    trades = pd.DataFrame(columns=['timestamp', 'type', 'price', 'units', 'value'])
    for i, row in signals.iterrows():
        if row['position'] == 1:  # 매수
            trade = {
                'timestamp': i,
                'type': 'BUY',
                'price': row['price'],
                'units': portfolio.loc[i, 'cash'] / row['price'] if i in portfolio.index else 0,
                'value': row['price'] * (portfolio.loc[i, 'cash'] / row['price'] if i in portfolio.index else 0)
            }
            trades = pd.concat([trades, pd.DataFrame([trade])], ignore_index=True)
        elif row['position'] == -1:  # 매도
            position_value = portfolio.loc[i, 'positions'] if i in portfolio.index else 0
            trade = {
                'timestamp': i,
                'type': 'SELL',
                'price': row['price'],
                'units': position_value / row['price'] if row['price'] != 0 else 0,
                'value': position_value
            }
            trades = pd.concat([trades, pd.DataFrame([trade])], ignore_index=True)
    
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
    1. **코인 선택**: 백테스팅할 코인을 선택합니다.
    2. **시간 프레임**: 분석할 시간 단위를 선택합니다.
    3. **트레이딩 전략**: 백테스팅에 사용할 전략을 선택합니다.
    4. **백테스팅 기간**: 과거 몇 일 동안의 데이터로 백테스팅할지 설정합니다.
    5. **초기 자본**: 백테스팅 시작 자본을 설정합니다.
    6. **전략 파라미터**: 선택한 전략에 맞는 파라미터를 조정합니다.
    7. **백테스팅 시작** 버튼을 클릭하여 결과를 확인합니다.
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
        RSI가 과매도 수준(기본값 30) 아래로 내려갈 때 매수하고, 
        과매수 수준(기본값 70) 위로 올라갈 때 매도하는 전략입니다.
        """)
    
    with col3:
        st.markdown("#### 볼린저 밴드 전략")
        st.markdown("""
        가격이 하단 밴드 아래로 내려갈 때 매수하고, 
        상단 밴드 위로 올라갈 때 매도하는 전략입니다.
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
            df = fetch_ohlcv(symbol, timeframe, since)
            
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
            
            # 백테스팅 실행
            portfolio, trades = backtest(signals, initial_capital)
            
            # 성과 지표 계산
            total_return = ((portfolio['total'].iloc[-1] / initial_capital) - 1) * 100
            max_drawdown = (portfolio['total'] / portfolio['total'].cummax() - 1).min() * 100
            
            # 승률 계산
            if len(trades) > 0:
                trades['profit'] = 0
                for i in range(0, len(trades), 2):
                    if i + 1 < len(trades):
                        buy_value = trades.iloc[i]['value']
                        sell_value = trades.iloc[i + 1]['value']
                        trades.loc[i + 1, 'profit'] = sell_value - buy_value
                
                wins = len(trades[trades['profit'] > 0])
                total_trades = len(trades[trades['profit'] != 0])
                win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
            else:
                win_rate = 0
                
            # 결과 표시
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("총 수익률", f"{total_return:.2f}%")
            col2.metric("최대 손실폭 (MDD)", f"{max_drawdown:.2f}%")
            col3.metric("승률", f"{win_rate:.2f}%")
            col4.metric("거래 횟수", f"{len(trades) // 2}")
            
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
            
            # 매수/매도 신호 표시
            buy_signals = signals[signals['position'] == 1]
            sell_signals = signals[signals['position'] == -1]
            
            fig.add_trace(
                go.Scatter(x=buy_signals.index, y=buy_signals['price'], name='매수', 
                           mode='markers', marker=dict(symbol='triangle-up', size=15, color='green')),
                row=1, col=1
            )
            
            fig.add_trace(
                go.Scatter(x=sell_signals.index, y=sell_signals['price'], name='매도', 
                           mode='markers', marker=dict(symbol='triangle-down', size=15, color='red')),
                row=1, col=1
            )
            
            # RSI 전략일 경우 매수/매도 신호도 fig2에 추가
            if strategy == "RSI":
                fig2.add_trace(
                    go.Scatter(x=buy_signals.index, y=buy_signals['price'], name='매수', 
                               mode='markers', marker=dict(symbol='triangle-up', size=15, color='green')),
                    row=1, col=1
                )
                
                fig2.add_trace(
                    go.Scatter(x=sell_signals.index, y=sell_signals['price'], name='매도', 
                               mode='markers', marker=dict(symbol='triangle-down', size=15, color='red')),
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
                yaxis_title='가격 (USDT)',
                height=800,
                xaxis_rangeslider_visible=False
            )
            
            # RSI 전략일 경우 fig2 레이아웃 설정
            if strategy == "RSI":
                fig2.update_layout(
                    title=f'백테스팅 결과: {symbol} - RSI 전략 ({strategy_params})',
                    xaxis_title='날짜',
                    yaxis_title='가격 (USDT)',
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
                st.dataframe(trades[['timestamp', 'type', 'price', 'units', 'value', 'profit']])
            
                # 거래 통계
                total_profit = trades['profit'].sum()
                avg_profit = trades[trades['profit'] != 0]['profit'].mean()
                max_profit = trades['profit'].max()
                max_loss = trades['profit'].min()
                
                st.subheader("거래 통계")
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("총 이익/손실", f"{total_profit:.2f} USDT")
                col2.metric("평균 이익/손실", f"{avg_profit:.2f} USDT")
                col3.metric("최대 이익", f"{max_profit:.2f} USDT")
                col4.metric("최대 손실", f"{max_loss:.2f} USDT")
                
                # 월별 성과
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
            else:
                st.warning("해당 기간과 전략에서는 거래가 발생하지 않았습니다. 파라미터를 조정해보세요.")
                
        except Exception as e:
            st.error(f"오류가 발생했습니다: {str(e)}")
            st.info("다른 코인, 시간 프레임 또는 기간을 선택해보세요.")

# 앱 정보 표시
with st.expander("앱 정보"):
    st.markdown("""
    ### 코인 백테스팅 시스템 v1.0
    
    이 앱은 암호화폐 트레이딩 전략을 테스트하기 위한 백테스팅 도구입니다.
    
    **사용된 라이브러리:**
    - Streamlit: 웹 인터페이스
    - CCXT: 암호화폐 거래소 API
    - Pandas/NumPy: 데이터 처리
    - Plotly: 데이터 시각화
    
    **주의사항:**
    이 시스템은 교육 및 연구 목적으로 제작되었으며, 실제 투자 결정에 사용하기 전에 철저한 검증이 필요합니다.
    과거 성과가 미래 성과를 보장하지 않습니다.
    """)