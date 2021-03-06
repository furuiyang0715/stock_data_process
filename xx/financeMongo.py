"""
finance 的 mongo 版本
"""
# 自测使用的代码段
import sys
_path = "/home/ruiyang/company_projects/demo/xx"
while _path in sys.path:
    sys.path.remove(_path)
path_ = "/home/ruiyang/company_projects/demo"
if not path_ in sys.path:
    sys.path.append(path_)

import datetime
import pandas
import numpy

from xx import connect_db, connect_coll
from xx.mapping import gen_factor2collection_map
from xx.full_tool import convert_11code
from xx.distribution import gen_factor_name_list, dis_collection2factor_map
from xx.full_tool import convert2datetime
from xx.JZdataMixin import TradeCalendar
from xx.factor import f
from xx.interface import AbstractJZData
from xx.full_config import full_bool_collection_map


class Finance(AbstractJZData):
    def __init__(self):
        self._db = connect_db()
        self.bool_collection = full_bool_collection_map
        self.factor2collection_map = gen_factor2collection_map(self.bool_collection)

    def fix_factor(self, stock_list: list, factor: f or list, start_date: str or datetime.date,
                   end_date: str or datetime.date):

        # 格式化参数
        stock_list = convert_11code(stock_list)
        collection2factor_map = dis_collection2factor_map(factor, self.factor2collection_map)
        start_date = convert2datetime(start_date)
        end_date = convert2datetime(end_date)
        end_date = end_date + datetime.timedelta(hours=23, minutes=59, seconds=59)

        # 查询停牌时间
        calendar = TradeCalendar().calendar(start_date.strftime("%Y%m%d"),
                                            end_date.strftime("%Y%m%d"))
        trading_calendar = calendar['date'][calendar['trade']]
        trading_calendar_index = pandas.DataFrame(trading_calendar,
                                                  columns=['index']).set_index('index')
        rett = trading_calendar_index.copy()

        # 确定要查询的集合和字段值
        collection, field = list(collection2factor_map.items())[0]
        field = field[0].name
        snap = ['SecuCode', 'PubDate', field]
        doc_snap = {k: 1 for k in snap}
        doc_snap["_id"] = 0

        # 查询
        db_coll = connect_coll(collection, self._db)
        ret = db_coll.find({'SecuCode': {'$in': stock_list},
                            "PubDate": {"$gte": start_date, "$lte": end_date}}, doc_snap)

        # 生成查询结果
        data = pandas.DataFrame(list(ret))

        # 对查询结果进行规范化
        if not data.empty:
            data[snap[1]] = data[snap[1]].map(lambda x: x.strftime('%Y-%m-%d'))
            data = data[snap]
            data.columns = ['stock', 'time', field]
            data = pandas.crosstab(data['time'], data['stock'], values=data[field], aggfunc='last')

        # 更新 rett
        rett = data.merge(rett, left_index=True, right_index=True, how='outer')
        rett = rett.fillna(method='pad')  # 先向后填充数据
        rett = rett.ix[trading_calendar_index.index]  # 再以日历限制一次日期

        to_concat_ret = pandas.DataFrame(dict(zip(stock_list, [1] * len(stock_list))),index=['1'])
        rett = pandas.concat([rett, to_concat_ret])
        rett = rett.drop(['1'])

        # 整理结果
        rett = rett.astype(float)
        rett = rett.to_records()
        rett.dtype.names = ['date'] + list(rett.dtype.names)[1:]

        # 暂时返回structured array，后面可以让用户选择返回pandas
        # 固定了因子的表格，表的行索引是股票，列索引是时间
        return numpy.array(rett)

    def fix_symbol(self, stock: str, factors: list or f, start_date: datetime.date or str,
                   end_date: datetime.date or str):
        # 格式化参数
        stock = convert_11code(stock)[0]
        collection2factor_map = dis_collection2factor_map(factors, self.factor2collection_map)
        start_date = convert2datetime(start_date)
        end_date = convert2datetime(end_date)
        end_date = end_date + datetime.timedelta(hours=23, minutes=59, seconds=59)

        # 查询停牌时间
        calendar = TradeCalendar().calendar(start_date.strftime("%Y%m%d"),
                                            end_date.strftime("%Y%m%d"))
        trading_calendar = calendar['date'][calendar['trade']]
        trading_calendar_index = pandas.DataFrame(trading_calendar,
                                                  columns=['index']).set_index('index')
        rett = trading_calendar_index.copy()

        # 确定要查询的集合和字段值
        _year = int(start_date.strftime("%Y")) - 1
        start_date = datetime.datetime(_year, 1, 1, 0, 0, 0)
        for collection in collection2factor_map:
            factor_name_list = gen_factor_name_list(collection2factor_map[collection])
            snap = ['PubDate', ]
            snap.extend(factor_name_list)
            doc_snap = {k: 1 for k in snap}
            doc_snap["_id"] = 0

            # 查询
            db_coll = connect_coll(collection, self._db)
            data = db_coll.find({'SecuCode': stock,
                                 "PubDate": {"$gte": start_date, "$lte": end_date}}, doc_snap)

            # 生成查询结果
            data = pandas.DataFrame(list(data))

            # 对查询结果进行规范化
            if not data.empty:
                data[snap[0]] = data[snap[0]].map(lambda x: x.strftime('%Y-%m-%d'))
                data = data[snap]
                data = data.set_index(snap[0])

            # 循环更新 rett
            rett = rett.merge(data, left_index=True, right_index=True, how='outer')
            rett[factor_name_list] = rett[factor_name_list].fillna(method='pad')  # 先向后填充数据
            rett = rett.ix[trading_calendar_index.index]  # 再以日历限制一次日期

        # 整理结果
        rett = rett.astype(float).to_records()
        rett.dtype.names = ['date'] + list(rett.dtype.names)[1:]

        return numpy.array(rett)

    def fix_time(self, stock_list: list or str, factors: list or f,
                 trade_date: datetime.date or str):
        # 格式化参数
        stock_list = convert_11code(stock_list)
        collection2factor_map = dis_collection2factor_map(factors, self.factor2collection_map)
        start_date = convert2datetime(trade_date)
        end_date = start_date + datetime.timedelta(hours=23, minutes=59, seconds=59)

        # 补充缺失股票
        rett = pandas.DataFrame(stock_list, columns=['stock']).set_index('stock')

        # 确定要查询的集合和字段值
        _year = int(start_date.strftime("%Y")) - 1
        start_date = datetime.datetime(_year, 1, 1, 0, 0, 0)
        for collection in collection2factor_map:
            factor_name_list = gen_factor_name_list(collection2factor_map[collection])
            snap = ['SecuCode', 'PubDate',]
            snap.extend(factor_name_list)
            doc_snap = {k: 1 for k in snap}
            doc_snap["_id"] = 0

            # 查询
            db_coll = connect_coll(collection, self._db)
            data = db_coll.find({'SecuCode': {'$in': stock_list},
                                 "PubDate": {"$gte": start_date, "$lte": end_date}}, doc_snap)

            # 生成查询结果
            data = pandas.DataFrame(list(data))

            # 对查询结果进行规范化
            if not data.empty:
                data = data[snap].set_index('PubDate')
                data.columns = ['stock'] + factor_name_list
            if len(data):
                data = data.groupby('stock')
                data = pandas.DataFrame([i[1].iloc[-1] for i in data]).set_index('stock')
            else:
                data = data.set_index('stock')

            # 循环更新 rett
            rett = rett.merge(data, left_index=True, right_index=True, how='outer')

        # 整理结果
        rett = rett.astype(float).to_records()
        rett.dtype.names = ['stock'] + list(rett.dtype.names)[1:]

        return numpy.array(rett)


if __name__ == "__main__":
    rundemo = Finance()
    stock_list = ["000001.XSHE", "000002.XSHE", "000543.XSHE"]
    s1 = datetime.datetime(2016, 1, 1)
    s2 = datetime.datetime(2017, 1, 1)
    f_list = [f("SubtotalOperateCashInflow"), f("CashEquivalents"), f("OtherCashInRelatedOperate")]
    ff = f("SubtotalOperateCashInflow")
    trade_date = datetime.datetime(2017, 5, 1)

    res1 = rundemo.fix_factor(stock_list, ff, s1, s2)
    print(res1)
    print()
    print()

    res2 = rundemo.fix_symbol("000702.XSHE", f_list, s1, s2)
    print(res2)
    print()
    print()

    res3 = rundemo.fix_time(stock_list, f_list, trade_date)
    print(res3)
    print()
    print()

    pass

