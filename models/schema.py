"""パチスロ台ごとのデータスキーマ定義.

1台・1日分のスロットデータを SlotData dataclass で管理し、
pandas DataFrame との相互変換をサポートする。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import pandas as pd

# ---------------------------------------------------------------------------
# DataFrame 変換時に適用する dtype 定義
# ---------------------------------------------------------------------------
SLOT_DATA_DTYPES: dict[str, str] = {
    "date": "datetime64[ns]",
    "shop_id": "str",
    "machine_name": "str",
    "unit_number": "int32",
    "g_count": "int32",
    "diff_payout": "int32",
    "bb_count": "int16",
    "rb_count": "int16",
}


# ---------------------------------------------------------------------------
# SlotData dataclass
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SlotData:
    """1台・1日分のスロットデータを格納する不変レコード.

    Attributes:
        date: 営業日 (datetime)
        shop_id: 店舗ID
        machine_name: 機種名
        unit_number: 台番号
        g_count: 回転数 (総ゲーム数)
        diff_payout: 差枚数 (プラスなら勝ち、マイナスなら負け)
        bb_count: BB (ビッグボーナス) 回数
        rb_count: RB (レギュラーボーナス) 回数
    """

    date: datetime
    shop_id: str
    machine_name: str
    unit_number: int
    g_count: int
    diff_payout: int
    bb_count: int
    rb_count: int

    # -- 変換ヘルパー --------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """辞書に変換する."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SlotData:
        """辞書からインスタンスを生成する.

        date が文字列の場合は ISO 形式としてパースする。
        """
        d = dict(data)
        if isinstance(d["date"], str):
            d["date"] = datetime.fromisoformat(d["date"])
        return cls(**d)


# ---------------------------------------------------------------------------
# DataFrame 変換
# ---------------------------------------------------------------------------
SLOT_DATA_COLUMNS: list[str] = list(SLOT_DATA_DTYPES.keys())


def to_dataframe(records: list[SlotData]) -> pd.DataFrame:
    """SlotData のリストを pandas DataFrame に変換する.

    空リストの場合でも正しいカラム・dtype を持った空 DataFrame を返す。
    """
    if not records:
        df = pd.DataFrame(columns=SLOT_DATA_COLUMNS)
    else:
        df = pd.DataFrame([r.to_dict() for r in records])

    # dtype を適用
    for col, dtype in SLOT_DATA_DTYPES.items():
        if col in df.columns:
            df[col] = df[col].astype(dtype)
    return df


def from_dataframe(df: pd.DataFrame) -> list[SlotData]:
    """pandas DataFrame を SlotData のリストに変換する."""
    records: list[SlotData] = []
    for _, row in df.iterrows():
        dt = row["date"]
        if isinstance(dt, pd.Timestamp):
            dt = dt.to_pydatetime()
        records.append(
            SlotData(
                date=dt,
                shop_id=str(row["shop_id"]),
                machine_name=str(row["machine_name"]),
                unit_number=int(row["unit_number"]),
                g_count=int(row["g_count"]),
                diff_payout=int(row["diff_payout"]),
                bb_count=int(row["bb_count"]),
                rb_count=int(row["rb_count"]),
            )
        )
    return records
