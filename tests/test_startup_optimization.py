import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
import TimePulse


def test_startup_migration_skips_when_already_migrated():
    data = {"startup_migration_version": 1, "alarms": []}
    lock = threading.Lock()
    with patch("TimePulse._remove_legacy_startup_files") as mock_files, \
         patch("TimePulse._remove_legacy_scheduled_tasks") as mock_tasks:
        result = TimePulse.run_startup_migration(data, lock)
        assert result is False
        mock_files.assert_not_called()
        mock_tasks.assert_not_called()


def test_startup_migration_does_not_stamp_version_on_failure():
    data = {"alarms": []}
    lock = threading.Lock()
    with patch("TimePulse._remove_legacy_startup_files", return_value=True), \
         patch("TimePulse._remove_legacy_scheduled_tasks", return_value=False), \
         patch("TimePulse.save_data") as mock_save:
        result = TimePulse.run_startup_migration(data, lock)
        assert result is False
        assert "startup_migration_version" not in data
        mock_save.assert_not_called()


def test_startup_migration_stamps_and_saves_version_on_success():
    data = {"alarms": []}
    lock = threading.Lock()
    with patch("TimePulse._remove_legacy_startup_files", return_value=True), \
         patch("TimePulse._remove_legacy_scheduled_tasks", return_value=True), \
         patch("TimePulse.save_data", return_value=True) as mock_save:
        result = TimePulse.run_startup_migration(data, lock)
        assert result is True
        assert data["startup_migration_version"] == 1
        mock_save.assert_called_once_with(data)


def test_refresh_password_controls_safe_before_settings_creation():
    app = SimpleNamespace(data={"password": None})
    # Must not raise AttributeError even if password_help_lbl does not exist
    TimePulse.AlarmApp._refresh_password_controls(app)


def test_lazy_tab_creation_builds_only_once():
    app = SimpleNamespace(
        tab_frames={},
        tab_btns={
            "alarms": Mock(),
            "timers": Mock(),
            "settings": Mock(),
        },
        _build_timer_tab=Mock(side_effect=lambda: app.tab_frames.update({"timers": Mock()})),
        _build_settings_tab=Mock(side_effect=lambda: app.tab_frames.update({"settings": Mock()})),
        _refresh_alarm_list=Mock(),
        _refresh_password_controls=Mock(),
    )

    # First visit builds tab
    TimePulse.AlarmApp._show_tab(app, "timers")
    assert app._build_timer_tab.call_count == 1
    assert "timers" in app.tab_frames

    # Second visit does not rebuild
    TimePulse.AlarmApp._show_tab(app, "timers")
    assert app._build_timer_tab.call_count == 1

    # First settings visit builds
    TimePulse.AlarmApp._show_tab(app, "settings")
    assert app._build_settings_tab.call_count == 1
    assert "settings" in app.tab_frames

    # Second settings visit does not rebuild
    TimePulse.AlarmApp._show_tab(app, "settings")
    assert app._build_settings_tab.call_count == 1


def test_alarm_checker_starts_in_on_first_idle_before_refresh():
    call_order = []
    app = SimpleNamespace(
        _shutting_down=False,
        _start_alarm_checker=Mock(side_effect=lambda: call_order.append("checker")),
        _refresh_alarm_list=Mock(side_effect=lambda batch_size: call_order.append(f"refresh_{batch_size}")),
        after_idle=Mock(side_effect=lambda fn: call_order.append("deferred")),
        _deferred_startup=Mock(),
    )

    TimePulse.AlarmApp._on_first_idle(app)

    assert call_order == ["checker", "refresh_25", "deferred"]
    app._start_alarm_checker.assert_called_once()
    app._refresh_alarm_list.assert_called_once_with(batch_size=25)


def test_render_alarm_cards_aborts_on_stale_generation_or_shutdown():
    app = SimpleNamespace(
        _shutting_down=False,
        _alarm_render_generation=2,
        alarm_scroll=Mock(winfo_exists=Mock(return_value=True)),
        winfo_exists=Mock(return_value=True),
        _alarm_card=Mock(),
        after=Mock(),
    )

    # Stale generation
    TimePulse.AlarmApp._render_alarm_cards(app, [{"id": "1"}], generation=1)
    app._alarm_card.assert_not_called()

    # Shutting down
    app._shutting_down = True
    TimePulse.AlarmApp._render_alarm_cards(app, [{"id": "1"}], generation=2)
    app._alarm_card.assert_not_called()


def test_setup_tray_schedules_polling():
    app = SimpleNamespace(
        _shutting_down=False,
        _tray_ready=False,
        _tray_starting=False,
        _tray_failed=False,
        _tray_ready_event=Mock(),
        _poll_tray_events=Mock(),
        after=Mock(),
    )

    with patch("threading.Thread") as mock_thread, \
         patch("TimePulse.ICON_PATH", "assets/TimePulse.ico"):
        mock_instance = Mock()
        mock_thread.return_value = mock_instance

        TimePulse.AlarmApp._setup_tray(app)

        assert app._tray_starting is True
        mock_instance.start.assert_called_once()
        app.after.assert_called_once_with(50, app._poll_tray_events)


def test_poll_tray_detects_dead_worker():
    thread = Mock(is_alive=Mock(return_value=False))
    app = SimpleNamespace(
        _shutting_down=False,
        _tray_events=Mock(get_nowait=Mock(side_effect=TimePulse.queue.Empty)),
        _tray_starting=True,
        _tray_thread=thread,
        _tray_failed=False,
        _tray_ready=False,
        _hide_requested=True,
        deiconify=Mock(),
        lift=Mock(),
        after=Mock(),
    )

    TimePulse.AlarmApp._poll_tray_events(app)

    assert app._tray_starting is False
    assert app._tray_failed is True
    assert app._hide_requested is False
    app.deiconify.assert_called_once()
    app.lift.assert_called_once()
    app.after.assert_not_called()
