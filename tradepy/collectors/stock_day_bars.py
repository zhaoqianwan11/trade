import numpy as np
import pandas as pd
from tqdm import tqdm

import tradepy
from tradepy import LOG
from tradepy.conversion import convert_code_to_market
from tradepy.depot.stocks import StocksDailyBarsDepot, StockListingDepot
from tradepy.depot.misc import CompanyNameChangesDepot
from tradepy.collectors.base import DayBarsCollector


class StockDayBarsCollector(DayBarsCollector):
    bars_depot_class = StocksDailyBarsDepot
    listing_depot_class = StockListingDepot

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name_changes_df: pd.DataFrame = CompanyNameChangesDepot.load()
        self.listing_df: pd.DataFrame = self.listing_depot_class.load()

    def download_and_process(self, code, start_date, end_date):
        try:
            df = tradepy.ak_api.get_stock_daily(code, start_date, end_date)
            if df.empty:
                return df
            df["market"] = convert_code_to_market(code)
            return self._patch_names(
                df,
                code,
            )
        except Exception:
            LOG.exception(f"获取{code}日K数据出错")
            raise

    def _patch_names(self, df: pd.DataFrame, code: str):
        try:
            changes_df = self.name_changes_df.loc[code]
        except KeyError:
            LOG.warn(
                f"Unable to look up the company name change history for stock {code}"
            )
            df["company"] = self.listing_df.loc["code", "company"]
            return df

        if isinstance(changes_df, pd.Series):
            # No name changes
            df["company"] = changes_df["company"]
            return df

        changes_df = changes_df.set_index("timestamp")

        # Name never changed to ST, so we don't care
        if not any("ST" in name for name in changes_df["company"]):
            return df

        # Patch the history names
        res = pd.merge(df, changes_df, how="left", on="timestamp")  # TODO
        res["company"].ffill(inplace=True)

        if res["company"].hasnans:
            lead_ts = res["timestamp"][res["company"].isna()].min()
            try:
                lead_name = next(
                    name
                    for date, name in changes_df.iloc[::-1].itertuples()
                    if date < lead_ts
                )
                res["company"].fillna(lead_name, inplace=True)
            except StopIteration:
                res["company"].bfill(inplace=True)

        return res

    def _compute_mkt_cap_percentile_ranks(self, df: pd.DataFrame):
        for _, day_df in tqdm(df.groupby(level="timestamp")):
            if ("mkt_cap_rank" in day_df) and (day_df["mkt_cap_rank"].notnull().all()):
                yield day_df
                continue

            mkt_cap_lst = [row.mkt_cap for row in day_df.itertuples()]

            mkt_cap_percentiles = np.percentile(mkt_cap_lst, q=range(100))
            day_df["mkt_cap_rank"] = [
                (mkt_cap_percentiles < v).sum() / len(mkt_cap_percentiles)
                for v in mkt_cap_lst
            ]
            yield day_df

    def run(
        self, batch_size=50, iteration_pause=5, selected_stocks=None, write_file=True
    ) -> pd.DataFrame:
        LOG.info("=============== 开始更新个股日K数据 ===============")
        jobs = list(
            job
            for job in self.jobs_generator()
            if (selected_stocks is None) or (job["code"] in selected_stocks)
        )

        results_gen = self.run_batch_jobs(
            jobs,
            batch_size,
            iteration_pause=iteration_pause,
            fun=self.download_and_process,
        )
        for args, bars_df in results_gen:
            if bars_df.empty:
                LOG.info(f"找不到{args['code']}日K数据. Args = {args}")
            else:
                code = args["code"]
                self.repo.append(bars_df, f"{code}.csv")

        LOG.info("计算个股的每日市值分位")
        df = self.repo.load(index_by="timestamp", fields="all")
        df = pd.concat(self._compute_mkt_cap_percentile_ranks(df))
        df.reset_index(inplace=True, drop=True)

        if write_file:
            LOG.info("保存中")
            for code, sub_df in df.groupby("code"):
                sub_df.drop("code", axis=1, inplace=True)
                assert isinstance(code, str)
                self.repo.save(sub_df, filename=code + ".csv")

        return df
