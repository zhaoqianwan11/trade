from tradepy.collectors.stock_listing import StocksListingCollector
from tradepy.collectors.adjust_factor import AdjustFactorCollector
from tradepy.collectors.market_index import BroadBasedIndexCollector

# 下载股票列表和复权因子
StocksListingCollector().run(batch_size=25) 
AdjustFactorCollector().run(batch_size=25)

# 下载宽基指数
BroadBasedIndexCollector().run()
import os

directory = 'D:\\zgy_1001\\trade\\database'
if not os.path.exists(directory):
    os.makedirs(directory)