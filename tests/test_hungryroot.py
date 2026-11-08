"""Tests with faked Hungryroot answers (shapes guessed from their web code)."""

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hungryroot.api import (
    HungryrootAuthError,
    HungryrootCaptchaRequired,
    parse_cookie_string,
)
from custom_components.hungryroot.const import CONF_COOKIE, DOMAIN
from custom_components.hungryroot.coordinator import parse_order

CLIENT = "custom_components.hungryroot.api.HungryrootClient"

ORDER = {
    "id": 555,
    "status": "scheduled",
    "delivery_date": "2026-11-12",
    "cutoff_datetime": "2026-11-09T23:59:00-05:00",
    "deadline_exceeded": False,
    "total": "89.50",
    "shipping_cost": "0.00",
    "products": [
        {"product": {"name": "Chicken Sausage"}, "quantity": 2},
        {"name": "Kale Salad Kit", "quantity": 1},
    ],
    "bundles": [
        {"pairing": {"name": "Sausage & Kale Bowl"}},
        {"pairing": None},
    ],
}


def test_parse_order():
    p = parse_order(ORDER)
    assert p["delivery_date"].isoformat() == "2026-11-12"
    assert p["cutoff"].hour == 23
    assert p["total"] == 89.5
    assert [i["name"] for i in p["items"]] == ["Chicken Sausage", "Kale Salad Kit"]
    assert p["recipes"] == ["Sausage & Kale Bowl"]


def test_parse_cookie():
    assert parse_cookie_string("cookie: sessionid=abc; csrftoken=xyz") == {
        "sessionid": "abc",
        "csrftoken": "xyz",
    }


async def test_login_flow(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "login"}
    )
    with (
        patch(f"{CLIENT}.login", return_value=None),
        patch(f"{CLIENT}.get_customer", return_value={"id": 42}),
        patch(f"{CLIENT}.cookie", new="sessionid=abc"),
        patch("custom_components.hungryroot.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_EMAIL: "me@example.com", CONF_PASSWORD: "pw"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_COOKIE: "sessionid=abc", CONF_EMAIL: "me@example.com"}
    assert result["result"].unique_id == "42"


async def test_captcha_falls_back_to_session(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "login"}
    )
    with patch(f"{CLIENT}.login", side_effect=HungryrootCaptchaRequired("captcha")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_EMAIL: "me@example.com", CONF_PASSWORD: "pw"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "session"
    assert "captcha" in result["description_placeholders"]["reason"]

    with patch(f"{CLIENT}.get_customer", side_effect=HungryrootAuthError("no")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_COOKIE: "sessionid=bad"}
        )
    assert result["errors"] == {"base": "invalid_session"}

    with (
        patch(f"{CLIENT}.get_customer", return_value={"id": 42}),
        patch("custom_components.hungryroot.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_COOKIE: "sessionid=good"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def _setup(hass, **patches):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="42", data={CONF_COOKIE: "sessionid=abc"}
    )
    entry.add_to_hass(hass)
    defaults = {
        "get_customer": {"id": 42},
        # Real layout seen 2026-11-08: orders nested under results.order
        "get_orders": {"count": 1, "next": None, "results": {"order": [ORDER], "tags": []}},
        "get_order": {"order": [ORDER], "tags": []},
    }
    defaults.update(patches)
    with (
        patch(f"{CLIENT}.get_customer", **_mock(defaults["get_customer"])),
        patch(f"{CLIENT}.get_orders", **_mock(defaults["get_orders"])),
        patch(f"{CLIENT}.get_order", **_mock(defaults["get_order"])),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _mock(val):
    return {"side_effect": val} if isinstance(val, Exception) else {"return_value": val}


async def test_sensors(hass):
    entry = await _setup(hass)
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert hass.states.get("sensor.hungryroot_next_delivery").state == "2026-11-12"
    items = hass.states.get("sensor.hungryroot_box_items")
    assert items.state == "2"
    assert items.attributes["items"][0]["name"] == "Chicken Sausage"
    assert hass.states.get("sensor.hungryroot_recipes_this_week").attributes["recipes"] == [
        "Sausage & Kale Bowl"
    ]
    assert hass.states.get("sensor.hungryroot_next_box_total").state == "89.5"
    assert hass.states.get("sensor.hungryroot_spend_last_10_orders").state == "89.5"
    assert hass.states.get("binary_sensor.hungryroot_box_editable") is not None


async def test_expired_session_starts_reauth(hass):
    entry = await _setup(hass, get_customer=HungryrootAuthError("expired"))
    assert entry.state is config_entries.ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_api_change_raises_repair(hass):
    from homeassistant.helpers import issue_registry as ir

    await _setup(hass, get_orders={"weird": True})
    assert ir.async_get(hass).async_get_issue(DOMAIN, "api_changed") is not None


async def test_reauth_updates_session(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="42", data={CONF_COOKIE: "sessionid=old"}
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "session"}
    )
    with (
        patch(f"{CLIENT}.get_customer", return_value={"id": 42}),
        patch("custom_components.hungryroot.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_COOKIE: "sessionid=new"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_COOKIE] == "sessionid=new"


async def test_reauth_rejects_other_account(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="42", data={CONF_COOKIE: "x=1"})
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "session"}
    )
    with patch(f"{CLIENT}.get_customer", return_value={"id": 99}):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_COOKIE: "sessionid=other"}
        )
    assert result["reason"] == "wrong_account"


def test_status_names():
    assert parse_order({"status": 20, "status_label": "Recurring"})["status"] == "Scheduled"
    assert parse_order({"status": 80})["status"] == "Out for delivery"
    assert parse_order({"status": 999, "status_label": "New Thing"})["status"] == "New Thing"
