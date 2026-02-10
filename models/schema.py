"""パチスロ台ごとのデータスキーマ定義."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional

import pandas as pd


@dataclass
class SlotRecord:
    """1台・1日分のスロットデータを格納するレコード.

    Attributes:
        date: 営業日
        hall_id: 店舗ID
        model_name: 機種名
        unit_no: 台番号
        spins: 回転数 (総ゲーム数)
        diff_medals: 差枚数 (プラスなら勝ち、マイナスなら負け)
        bb_count: BB (ビッグボーナス) 回数
        rb_count: RB (レギュラーボーナス) 回数
    """

    date: date
    hall_id: str
    model_name: str
    unit_no: int
    spins: int
    diff_medals: int
    bb_count: int
    rb_count: int

    def to_dict(self) -> dict:
        """辞書に変換する."""
        d = asdict(self)
        d["date"] = self.date.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> SlotRecord:
        """辞書からインスタンスを生成する."""
        d = dict(data)
        if isinstance(d["date"], str):
            d["date"] = date.fromisoformat(d["date"])
        return cls(**d)


def records_to_dataframe(records: list[SlotRecord]) -> pd.DataFrame:
    """SlotRecord のリストを pandas DataFrame に変換する."""
    if not records:
        return pd.DataFrame(
            columns=[
                "date",
                "hall_id",
                "model_name",
                "unit_no",
                "spins",
                "diff_medals",
                "bb_count",
                "rb_count",
            ]
        )
    return pd.DataFrame([r.to_dict() for r in records])
