import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.qt_hybrid_app import AppBridge, _group_route_rows


class NewScheduleStatusTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        db_patch = patch.object(database, "_db_path", return_value=str(Path(directory.name) / "meter.db"))
        db_patch.start()
        self.addCleanup(db_patch.stop)
        database.init_db()
        self.today = date.today()
        self.old_start = (self.today - timedelta(days=10)).isoformat()
        self.old_due = (self.today - timedelta(days=3)).isoformat()
        self.new_start = self.today.isoformat()
        self.new_due = (self.today + timedelta(days=7)).isoformat()
        self._add_schedule(101, self.old_start, self.old_due)
        self._add_consumer(1, 101, True)
        self._add_consumer(2, 101, False)
        self._add_consumer(3, 101, False)

    def _add_schedule(self, schedule_id, start, due):
        database.replace_reading_schedules_from_sync([{
            "schedule_id": schedule_id, "start_date": start, "due_date": due,
            "billing_month": self.today.strftime("%B %Y"), "zone_name": "Zone 1",
            "meter_reader_id": 12, "status": "Scheduled",
        }], 12, start, due)

    def _add_consumer(self, consumer_id, schedule_id, is_read):
        database.replace_consumers_from_sync([{
            "id": consumer_id, "meter_no": f"MTR-{consumer_id}",
            "acct_no": f"ACCT-{consumer_id}", "name": f"Consumer {consumer_id}",
            "zone_name": "Zone 1", "schedule_id": schedule_id,
            "is_read": is_read, "reading_status": "valid" if is_read else "pending",
            "reading_sync_status": "synced" if is_read else "pending",
        }])

    def _view(self, group):
        view = SimpleNamespace(
            _meter_reader_account_id="12", selectedBillingDate=self.new_start,
            _route_schedules=lambda: group["viewSchedules"],
        )
        view._selected_route_consumer_rows = lambda: AppBridge._selected_route_consumer_rows(view)
        return view

    def test_new_route_shows_new_unread_and_only_unread_carry_over(self):
        self._add_schedule(202, self.new_start, self.new_due)
        self._add_consumer(1, 202, False)
        self._add_consumer(2, 202, False)
        grouped = _group_route_rows(database.get_assigned_routes(12), today=self.today)
        current = next(group for group in grouped if group["startDate"] == self.new_start)
        current_rows = AppBridge._selected_route_consumer_rows(self._view(current))
        self.assertEqual(
            {(row["schedule_id"], row["id"], row["is_read"]) for row in current_rows},
            {(101, 3, 0), (202, 1, 0), (202, 2, 0)},
        )
        search_rows = AppBridge._search_selected_route(self._view(current), "Consumer 1", 10, False)
        self.assertEqual([(row["schedule_id"], row["id"]) for row in search_rows], [(202, 1)])

        past = next(group for group in grouped if group["startDate"] == self.old_start)
        past_rows = AppBridge._selected_route_consumer_rows(self._view(past))
        self.assertEqual({(row["id"], row["is_read"]) for row in past_rows}, {(1, 1), (2, 0), (3, 0)})
        reassigned = AppBridge._search_selected_route(self._view(current), "Consumer 2", 10, False)
        self.assertEqual([(row["schedule_id"], row["id"]) for row in reassigned], [(202, 2)])

    def _assignment_view(self):
        def signal():
            return SimpleNamespace(emit=lambda *args: None)

        view = SimpleNamespace(
            _meter_reader_account_id="12", _assigned_routes=[], _selected_route_id="",
            _route_selected_by_user=False, _zones=[], _selected_zone="",
            _selected_route_billing_date="", assignedRoutesChanged=signal(),
            selectedRouteChanged=signal(), zonesChanged=signal(), selectedZoneChanged=signal(),
            _refresh_search_suggestions=lambda: None, _refresh_zone_consumers=lambda: None,
            update_stats=lambda: None,
        )
        view._selected_route = lambda: next(
            (r for r in view._assigned_routes if r["scheduleId"] == view._selected_route_id), {}
        )
        return view

    def test_overdue_route_marks_only_unread_consumers_overdue(self):
        route = database.get_assigned_routes(12)[0]
        self.assertEqual(route["display_status"], "Overdue")
        self.assertEqual(route["unread_count"], 2)
        rows = database.get_zone_consumers_with_status("Zone 1", meter_reader_id=12, schedule_id=101)
        self.assertEqual(
            {row["id"]: row["deadline_status"] for row in rows},
            {1: "Completed", 2: "Overdue 3d", 3: "Overdue 3d"},
        )

    def test_finishing_overdue_route_offline_refreshes_completed_status(self):
        view = self._assignment_view()
        AppBridge._refresh_local_assignment_views(view)
        self.assertEqual(view._selected_route()["status"], "Overdue")
        selected_id = view._selected_route_id
        view._route_selected_by_user = True
        for consumer_id, sync_status in ((2, "pending"), (3, "failed")):
            database.save_reading(
                consumer_id, 10, 10, schedule_id=101,
                schedule_date=self.old_start, schedule_due_date=self.old_due,
                reading_sync_status=sync_status, sync_reading_id=f"saved-{consumer_id}",
            )
            # A stale API snapshot must not undo a locally saved reading.
            self._add_consumer(consumer_id, 101, False)
        AppBridge._refresh_local_assignment_views(view)
        self.assertEqual(view._selected_route_id, selected_id)
        self.assertEqual(view._selected_route()["status"], "Completed")
        route = database.get_assigned_routes(12)[0]
        self.assertEqual((route["assignment_count"], route["unread_count"]), (3, 0))
        rows = database.get_zone_consumers_with_status("Zone 1", meter_reader_id=12, schedule_id=101)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["deadline_status"] == "Completed" for row in rows))

        database.update_reading_sync_state("saved-2", "conflict", "rejected")
        AppBridge._refresh_local_assignment_views(view)
        self.assertEqual(view._selected_route()["status"], "Overdue")
        self.assertEqual(database.get_assigned_routes(12)[0]["unread_count"], 1)

    def test_expired_route_without_cached_assignments_is_not_completed(self):
        self._add_schedule(202, self.old_start, self.old_due)
        route = next(row for row in database.get_assigned_routes(12) if row["schedule_id"] == 202)
        self.assertEqual(route["assignment_count"], 0)
        self.assertEqual(route["display_status"], "Overdue")

    def test_refresh_selects_new_route_unless_reader_chose_a_past_route(self):
        view = self._assignment_view()
        AppBridge._refresh_local_assignment_views(view)
        old_route_id = view._selected_route_id
        self._add_schedule(202, self.new_start, self.new_due)
        self._add_consumer(1, 202, False)
        AppBridge._refresh_local_assignment_views(view)
        self.assertNotEqual(view._selected_route_id, old_route_id)
        self.assertEqual(view._selected_route()["startDate"], self.new_start)
        view._selected_route_id = old_route_id
        view._route_selected_by_user = True
        AppBridge._refresh_local_assignment_views(view)
        self.assertEqual(view._selected_route_id, old_route_id)


if __name__ == "__main__":
    unittest.main()
