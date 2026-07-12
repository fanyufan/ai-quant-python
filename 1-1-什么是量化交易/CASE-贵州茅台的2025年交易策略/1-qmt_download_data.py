# -*- coding: utf-8 -*-
"""
QMT 数据下载脚本（双后端：miniQMT / QMT HTTP）

下载贵州茅台（600519.SH）历史日线（前复权），保存到本地 CSV，供后续策略分析。

通过环境变量 WUCAI_QMT 切换数据源（没设置就默认 QMT HTTP）：
  WUCAI_QMT=miniqmt → 用 xtquant（老 miniQMT，需装 xtquant + QMT_PATH）
  WUCAI_QMT=qmt（默认）→ 用 QMT HTTP 桥（需先在 QMT 里跑 QMT_Server_API.py）

Author：@跟陈博士学AI
"""
import os
import time
import pandas as pd

# === 后端开关：读 WUCAI_QMT，没有就默认 qmt ===
USE_MINIQMT = os.getenv("WUCAI_QMT", "qmt").strip().lower() in ("miniqmt", "xtquant", "mini_qmt")


# 数据下载参数配置
STOCK_CODE = '600519.SH'  # 贵州茅台股票代码
STOCK_NAME = '贵州茅台'
DATA_START = '20240101'   # 数据开始日期（需要足够的历史数据计算MACD）
DATA_END = '20251231'     # 数据结束日期


def _fetch_xtquant():
    """miniQMT 后端：返回 {field: [按日期排序的值...]}, dates: ['YYYYMMDD', ...]"""
    from xtquant import xtdata
    # 步骤1：下载历史数据
    print("步骤1：下载历史数据...")
    try:
        xtdata.download_history_data(stock_code=STOCK_CODE, period='1d', start_time=DATA_START)
        print("下载完成，等待数据写入...")
        time.sleep(2)
    except Exception as e:
        print(f"下载数据时出现警告：{e}")
        print("继续尝试获取数据...")

    # 步骤2：获取历史数据（前复权）
    print("\n步骤2：获取历史行情数据...")
    res = xtdata.get_market_data(
        stock_list=[STOCK_CODE], period='1d',
        start_time=DATA_START, end_time='', count=-1,
        dividend_type='front',   # 前复权
        fill_data=True
    )
    if not res or 'close' not in res or STOCK_CODE not in res['close'].index:
        return None
    dates = res['close'].columns.tolist()
    out = {'close': res['close'].loc[STOCK_CODE].values}
    for fld in ('open', 'high', 'low', 'volume'):
        df = res.get(fld)
        if df is not None and STOCK_CODE in df.index:
            out[fld] = df.loc[STOCK_CODE].values
    return dates, out


def _fetch_qmt_http():
    """QMT HTTP 后端：调 /api/data/market_data，返回 (dates, {field: [values]})"""
    import requests
    base_url = os.getenv("QMT_BASE_URL", "http://127.0.0.1:15588").rstrip("/")
    token = os.getenv("QMT_TOKEN", "learning_ai_with_dr_chen")
    print("步骤1-2：通过 QMT HTTP 拉取历史行情（前复权）...")
    resp = requests.post(
        f"{base_url}/api/data/market_data",
        headers={"Content-Type": "application/json", "X-Token": token},
        json={
            "stock_code": STOCK_CODE,
            "fields": "open,high,low,close,volume",
            "period": "1d",
            "start_time": DATA_START,
            "end_time": "",
            "count": -1,
            "dividend_type": "front",   # 前复权
        },
        timeout=120,
    )
    resp.raise_for_status()
    body = resp.json()
    if isinstance(body, dict) and body.get("error"):
        print(f"错误：{body['error']}")
        return None
    # Server 返回 {data: {field: {timetag: value}}}（单股时 value 是数值；
    # 多股时 value 是 {stock: value}）。两种都兼容。
    data = body.get("data") or {}
    close_map = data.get("close", {})
    if not close_map:
        return None
    dates = sorted(close_map.keys())   # ['20240101', '20240102', ...]
    out = {}
    for fld in ('close', 'open', 'high', 'low', 'volume'):
        m = data.get(fld, {})
        col = []
        for t in dates:
            v = m.get(t)
            col.append(v.get(STOCK_CODE) if isinstance(v, dict) else v)
        out[fld] = col
    return dates, out


def download_stock_data():
    """下载股票历史数据并保存到CSV文件"""
    print(f"开始下载股票数据")
    print(f"股票：{STOCK_NAME}({STOCK_CODE})")
    print(f"日期范围：{DATA_START} 至 {DATA_END}")
    print(f"后端：{'miniQMT (xtquant)' if USE_MINIQMT else 'QMT HTTP'}")
    print("-" * 60)

    try:
        result = _fetch_xtquant() if USE_MINIQMT else _fetch_qmt_http()
        if result is None:
            print("错误：无法获取历史数据")
            return None
        dates, fields_map = result

        # 构建数据 DataFrame
        data_dict = {'date': dates, 'close': fields_map.get('close')}
        for fld in ('open', 'high', 'low', 'volume'):
            if fld in fields_map:
                data_dict[fld] = fields_map[fld]
        df = pd.DataFrame(data_dict)

        # 转换日期格式（timetag 为 'YYYYMMDD' 字符串）
        df['date'] = pd.to_datetime(df['date'], format='%Y%m%d', errors='coerce')

        # 过滤掉无效数据
        df = df.dropna(subset=['date', 'close'])
        df = df.sort_values('date').reset_index(drop=True)

        print(f"成功获取 {len(df)} 条历史数据")
        print(f"数据日期范围：{df['date'].iloc[0].strftime('%Y-%m-%d')} 至 {df['date'].iloc[-1].strftime('%Y-%m-%d')}")

        # 步骤3：保存到CSV文件
        print("\n步骤3：保存数据到CSV文件...")
        output_dir = os.path.join(os.getcwd(), 'data')
        os.makedirs(output_dir, exist_ok=True)

        output_file = os.path.join(output_dir, f'{STOCK_CODE.replace(".", "_")}_daily.csv')
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"数据已保存至：{output_file}")

        # 显示数据预览
        print("\n数据预览（前5行）：")
        print(df.head().to_string(index=False))
        print("\n数据预览（后5行）：")
        print(df.tail().to_string(index=False))

        # 显示数据统计
        print("\n数据统计信息：")
        print(f"  总记录数：{len(df)}")
        print(f"  收盘价范围：{df['close'].min():.2f} - {df['close'].max():.2f}")
        if 'volume' in df.columns:
            print(f"  成交量范围：{df['volume'].min():,.0f} - {df['volume'].max():,.0f}")

        return output_file

    except Exception as e:
        print(f"下载数据过程中发生错误：{e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    result = download_stock_data()

    if result:
        print("\n" + "=" * 60)
        print("数据下载完成!")
        print(f"数据文件：{result}")
        print("=" * 60)
        print("\n提示：现在可以运行 6b-macd_strategy_analysis.py 进行策略分析")
    else:
        print("\n数据下载失败，请检查错误信息。")
