FROM python:3.12-slim
WORKDIR /app
COPY kalshi_btc15m_dual45_paper.py /app/
ENV PYTHONUNBUFFERED=1
ENV PAPER_STATE_PATH=/data/kalshi_btc15m_dual45_state.json
CMD ["python", "kalshi_btc15m_dual45_paper.py"]
