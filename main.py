import os
from datetime import datetime, timedelta
import requests
from pykrx import stock
from openai import OpenAI
import telegram
from telegram import Bot
import asyncio

# 설정
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"
OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"
INTEREST_STOCKS = ["005930", "000660", "035420", "051910"]  # 삼성전자, SK하이닉스, NAVER, LG화학

class StockNewsBot:
    def __init__(self):
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.openai_client = OpenAI(api_key=OPENAI_API_KEY)
        self.today = datetime.now().strftime("%Y%m%d")
        self.yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    
    def get_stock_info(self, ticker):
        """종목 정보 및 변동률 조회"""
        try:
            # 종목명 조회
            stock_name = stock.get_market_ticker_name(ticker)
            
            # 오늘과 어제 종가 조회
            df = stock.get_market_ohlcv_by_date(self.yesterday, self.today, ticker)
            
            if len(df) < 2:
                # 데이터가 부족한 경우 (주말 등)
                return None
            
            today_close = df.iloc[-1]['종가']
            yesterday_close = df.iloc[-2]['종가']
            change_rate = ((today_close - yesterday_close) / yesterday_close) * 100
            
            return {
                "name": stock_name,
                "ticker": ticker,
                "close": today_close,
                "change_rate": change_rate
            }
        except Exception as e:
            print(f"종목 {ticker} 정보 조회 실패: {e}")
            return None
    
    def get_stock_news(self, ticker, stock_name):
        """네이버 금융 뉴스 크롤링"""
        try:
            url = f"https://finance.naver.com/item/news_news.naver?code={ticker}&page=1"
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers)
            
            # 간단한 파싱 (실제로는 BeautifulSoup 사용 권장)
            news_list = []
            
            # 임시: 직접 링크 생성
            news_url = f"https://finance.naver.com/item/news.naver?code={ticker}"
            news_list.append({
                "title": f"{stock_name} 관련 뉴스",
                "url": news_url
            })
            
            return news_list
        except Exception as e:
            print(f"뉴스 조회 실패: {e}")
            return []
    
    def summarize_news_with_openai(self, stock_name, news_title, change_rate):
        """OpenAI API로 뉴스 요약"""
        try:
            prompt = f"""
            다음 정보를 바탕으로 간단하게 2-3문장으로 요약해주세요:
            
            종목명: {stock_name}
            전일 대비 변동률: {change_rate:+.2f}%
            뉴스 제목: {news_title}
            
            투자자 관점에서 핵심 포인트만 짧게 요약해주세요.
            """
            
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
            )

            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"OpenAI 요약 실패: {e}")
            return "요약을 생성할 수 없습니다."
    
    def get_top_sector(self):
        """가장 많이 오른 섹터와 주도 종목 찾기"""
        try:
            # 업종별 등락률 조회
            sectors = stock.get_index_ohlcv_by_date(self.yesterday, self.today, "1001")  # KOSPI
            
            # 섹터별 상위 종목 (실제로는 더 정교한 로직 필요)
            # 시가총액 상위 종목 조회
            top_stocks = stock.get_market_cap_by_ticker(self.today, market="ALL")
            top_stocks = top_stocks.sort_values('등락률', ascending=False).head(10)
            
            result = []
            for idx, row in top_stocks.head(3).iterrows():
                stock_name = stock.get_market_ticker_name(idx)
                result.append({
                    "ticker": idx,
                    "name": stock_name,
                    "change_rate": row['등락률']
                })
            
            return result
        except Exception as e:
            print(f"섹터 분석 실패: {e}")
            return []
    
    async def send_telegram_message(self, message):
        """텔레그램 메시지 전송"""
        try:
            await self.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=message,
                parse_mode='HTML',
                disable_web_page_preview=False
            )
            print("텔레그램 메시지 전송 완료")
        except Exception as e:
            print(f"텔레그램 전송 실패: {e}")
    
    def create_report(self):
        """시황 리포트 생성"""
        report = f"📊 <b>오늘의 주식 시황</b> ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n"
        
        # 1. 관심 종목 분석
        report += "🎯 <b>관심 종목</b>\n"
        report += "=" * 30 + "\n"
        
        for ticker in INTEREST_STOCKS:
            info = self.get_stock_info(ticker)
            if not info:
                continue
            
            # 변동률에 따른 이모지
            emoji = "🔴" if info['change_rate'] < 0 else "🟢" if info['change_rate'] > 0 else "⚪"
            
            report += f"\n{emoji} <b>{info['name']}</b> ({ticker})\n"
            report += f"종가: {info['close']:,}원 ({info['change_rate']:+.2f}%)\n"
            
            # 뉴스 링크
            news_list = self.get_stock_news(ticker, info['name'])
            if news_list:
                news = news_list[0]
                report += f"📰 뉴스: <a href='{news['url']}'>{news['title']}</a>\n"
                
                # OpenAI로 요약
                summary = self.summarize_news_with_openai(
                    info['name'], 
                    news['title'], 
                    info['change_rate']
                )
                report += f"💡 요약: {summary}\n"
        
        # 2. 상승 주도 종목
        report += "\n\n📈 <b>오늘의 강세 종목 TOP 3</b>\n"
        report += "=" * 30 + "\n"
        
        top_stocks = self.get_top_sector()
        for stock_info in top_stocks:
            report += f"🌟 {stock_info['name']} ({stock_info['ticker']}): "
            report += f"{stock_info['change_rate']:+.2f}%\n"
        
        return report
    
    async def run(self):
        """메인 실행 함수"""
        print("주식 시황 분석 시작...")
        report = self.create_report()
        print("\n생성된 리포트:\n")
        print(report)
        print("\n텔레그램 전송 중...")
        await self.send_telegram_message(report)
        print("완료!")

# 실행
async def main():
    bot = StockNewsBot()
    await bot.run()

if __name__ == "__main__":
    # 실행 방법
    asyncio.run(main())
