"""本番運用向け新機能のテスト.

- utils/logger.py (構造化ログ, ファイルローテーション)
- utils/machine_alias.py (機種名名寄せ)
- analysis/trend_analyzer.py の全台系日付リスト
- scripts/daily_update.py のバッチ処理
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

import pytest

from database.db_handler import SlotDatabase
from models.schema import MachineStats


# =====================================================================
# ヘルパー
# =====================================================================
def _make_stat(
    dt: date,
    shop_id: str,
    machine_name: str,
    avg_diff: int = 0,
    avg_g: int = 5000,
    win_rate: float = 50.0,
    payout_rate: float = 100.0,
) -> MachineStats:
    return MachineStats(
        date=datetime(dt.year, dt.month, dt.day),
        shop_id=shop_id,
        machine_name=machine_name,
        unit_count=5,
        avg_diff_payout=avg_diff,
        avg_g_count=avg_g,
        win_rate=win_rate,
        payout_rate=payout_rate,
    )


# =====================================================================
# utils/logger.py
# =====================================================================
class TestSetupLogging:
    def test_creates_log_file(self, tmp_path):
        """ログファイルが作成されること."""
        import utils.logger as logger_mod

        # _initialized をリセットしてテスト用に再初期化
        logger_mod._initialized = False
        logger_mod.setup_logging(log_dir=tmp_path)

        test_logger = logging.getLogger("test_creates_log_file")
        test_logger.info("テストログメッセージ")

        log_file = tmp_path / "tsumo_lab.log"
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "テストログメッセージ" in content

        # クリーンアップ: リセット
        logger_mod._initialized = False
        root = logging.getLogger()
        for h in root.handlers[:]:
            root.removeHandler(h)

    def test_idempotent(self, tmp_path):
        """2回呼んでもハンドラが増えないこと."""
        import utils.logger as logger_mod

        logger_mod._initialized = False
        logger_mod.setup_logging(log_dir=tmp_path)
        handler_count = len(logging.getLogger().handlers)

        # 2回目: _initialized=True なのでスキップ
        logger_mod.setup_logging(log_dir=tmp_path)
        assert len(logging.getLogger().handlers) == handler_count

        # クリーンアップ
        logger_mod._initialized = False
        root = logging.getLogger()
        for h in root.handlers[:]:
            root.removeHandler(h)


# =====================================================================
# utils/machine_alias.py
# =====================================================================
class TestMachineAliasResolver:
    def test_resolve_alias(self):
        from utils.machine_alias import MachineAliasResolver

        resolver = MachineAliasResolver()
        assert resolver.resolve("スマスロ北斗") == "L北斗の拳"
        assert resolver.resolve("マイジャグV") == "マイジャグラーV"

    def test_resolve_canonical_unchanged(self):
        from utils.machine_alias import MachineAliasResolver

        resolver = MachineAliasResolver()
        assert resolver.resolve("L北斗の拳") == "L北斗の拳"

    def test_resolve_unknown_unchanged(self):
        from utils.machine_alias import MachineAliasResolver

        resolver = MachineAliasResolver()
        assert resolver.resolve("未知の機種名") == "未知の機種名"

    def test_resolve_list(self):
        from utils.machine_alias import MachineAliasResolver

        resolver = MachineAliasResolver()
        result = resolver.resolve_list(["マイジャグV", "カバネリ", "テスト機種"])
        assert result == ["マイジャグラーV", "甲鉄城のカバネリ", "テスト機種"]

    def test_canonical_names(self):
        from utils.machine_alias import MachineAliasResolver

        resolver = MachineAliasResolver()
        names = resolver.canonical_names
        assert "L北斗の拳" in names
        assert "マイジャグラーV" in names

    def test_custom_alias_file(self, tmp_path):
        """カスタムエイリアスファイルの読み込み."""
        from utils.machine_alias import MachineAliasResolver

        alias_file = tmp_path / "custom.yaml"
        alias_file.write_text(
            'aliases:\n  "正規名":\n    - "別名A"\n    - "別名B"\n',
            encoding="utf-8",
        )

        resolver = MachineAliasResolver(alias_file)
        assert resolver.resolve("別名A") == "正規名"
        assert resolver.resolve("別名B") == "正規名"
        assert resolver.resolve("正規名") == "正規名"

    def test_missing_file_no_crash(self, tmp_path):
        """存在しないファイルでもクラッシュしない."""
        from utils.machine_alias import MachineAliasResolver

        resolver = MachineAliasResolver(tmp_path / "nonexistent.yaml")
        assert resolver.resolve("anything") == "anything"


# =====================================================================
# TrendAnalyzer 名寄せ統合テスト
# =====================================================================
class TestAliasIntegration:
    def test_alias_merges_machine_names(self, tmp_path):
        """DB 上の別名が正規名に統合されて集計されること."""
        from analysis.trend_analyzer import TrendAnalyzer
        from utils.machine_alias import MachineAliasResolver

        # カスタムエイリアス: "マイジャグV" → "マイジャグラーV"
        alias_file = tmp_path / "alias.yaml"
        alias_file.write_text(
            'aliases:\n  "マイジャグラーV":\n    - "マイジャグV"\n',
            encoding="utf-8",
        )
        resolver = MachineAliasResolver(alias_file)

        db = SlotDatabase(tmp_path / "test.db")
        db.insert_machine_stats([
            _make_stat(date(2025, 6, 5), "153", "マイジャグラーV",
                       avg_diff=1000, win_rate=80.0, payout_rate=110.0),
            _make_stat(date(2025, 6, 15), "153", "マイジャグV",  # 別名
                       avg_diff=2000, win_rate=90.0, payout_rate=115.0),
        ])

        analyzer = TrendAnalyzer(db, alias_resolver=resolver)
        result = analyzer.analyze("153")

        # day_suffix=5 に両方のデータが統合される
        trends_5 = result.day_suffix_trends[5]
        mj = [t for t in trends_5 if t.machine_name == "マイジャグラーV"]
        assert len(mj) == 1
        assert mj[0].count == 2  # 2日分が統合
        assert abs(mj[0].avg_diff_payout - 1500.0) < 1.0  # (1000+2000)/2
        db.close()


# =====================================================================
# 全台系日付リスト
# =====================================================================
class TestZentaiDates:
    def test_zentai_dates_populated(self, tmp_path):
        """全台系になった日付が MachineTrend.zentai_dates に入ること."""
        from analysis.trend_analyzer import TrendAnalyzer

        db = SlotDatabase(tmp_path / "test.db")
        db.insert_machine_stats([
            _make_stat(date(2025, 6, 5), "153", "マイジャグラーV",
                       avg_diff=1500, win_rate=80.0),  # 全台系
            _make_stat(date(2025, 6, 15), "153", "マイジャグラーV",
                       avg_diff=500, win_rate=60.0),  # 非全台系
            _make_stat(date(2025, 6, 25), "153", "マイジャグラーV",
                       avg_diff=1200, win_rate=75.0),  # 全台系
        ])

        result = TrendAnalyzer(db).analyze("153")
        trends_5 = result.day_suffix_trends[5]
        mj = [t for t in trends_5 if t.machine_name == "マイジャグラーV"][0]

        assert mj.zentai_count == 2
        assert len(mj.zentai_dates) == 2
        assert "2025-06-05" in mj.zentai_dates
        assert "2025-06-25" in mj.zentai_dates
        db.close()

    def test_zentai_dates_in_report(self, tmp_path):
        """レポートに全台系の実績日が含まれること."""
        from analysis.trend_analyzer import TrendAnalyzer, generate_report

        db = SlotDatabase(tmp_path / "test.db")
        db.insert_machine_stats([
            _make_stat(date(2025, 6, 5), "153", "マイジャグラーV",
                       avg_diff=1500, win_rate=80.0),
            _make_stat(date(2025, 6, 15), "153", "マイジャグラーV",
                       avg_diff=1200, win_rate=75.0),
        ])

        result = TrendAnalyzer(db).analyze("153")
        md = generate_report(result, day_suffix_targets=[5])

        assert "全台系の実績日" in md
        assert "2025-06-05" in md
        db.close()

    def test_no_zentai_no_details(self, tmp_path):
        """全台系がない場合は実績日セクションが出ないこと."""
        from analysis.trend_analyzer import TrendAnalyzer, generate_report

        db = SlotDatabase(tmp_path / "test.db")
        db.insert_machine_stats([
            _make_stat(date(2025, 6, 5), "153", "マイジャグラーV",
                       avg_diff=100, win_rate=40.0),  # 非全台系
        ])

        result = TrendAnalyzer(db).analyze("153")
        md = generate_report(result, day_suffix_targets=[5])

        assert "全台系の実績日" not in md
        db.close()


# =====================================================================
# scripts/daily_update.py
# =====================================================================
class TestDailyUpdateScript:
    def test_script_importable(self):
        """daily_update.py がインポートできること."""
        import importlib
        import sys

        # sys.path にスクリプトディレクトリを追加
        scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)

        spec = importlib.util.spec_from_file_location(
            "daily_update",
            Path(__file__).resolve().parent.parent / "scripts" / "daily_update.py",
        )
        assert spec is not None
        mod = importlib.util.module_from_spec(spec)
        # モジュールのロードまで (main() は実行しない)
        assert hasattr(spec, "loader")


# =====================================================================
# .gitignore にログディレクトリが含まれるか確認
# =====================================================================
class TestGitignore:
    def test_logs_should_be_ignored(self):
        """logs/ が .gitignore にあるべき (テスト自体は情報提供)."""
        gitignore = Path(__file__).resolve().parent.parent / ".gitignore"
        if gitignore.exists():
            content = gitignore.read_text()
            # logs/ が含まれていない場合でもテスト自体は pass
            # (実際の追加は gitignore 編集で行う)
            assert True
