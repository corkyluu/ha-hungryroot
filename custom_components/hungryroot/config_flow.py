"""Login screens for Hungryroot: email + password, with a paste-session fallback."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    HungryrootAuthError,
    HungryrootCaptchaRequired,
    HungryrootClient,
    HungryrootError,
)
from .const import (
    CONF_COOKIE,
    CONF_SCAN_HOURS,
    DEFAULT_SCAN_HOURS,
    DOMAIN,
    MAX_SCAN_HOURS,
    MIN_SCAN_HOURS,
)

_LOGGER = logging.getLogger(__name__)

LOGIN_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
        ),
    }
)

SESSION_SCHEMA = vol.Schema(
    {vol.Required(CONF_COOKIE): TextSelector(TextSelectorConfig(multiline=True))}
)


class HungryrootConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a Hungryroot account."""

    VERSION = 1

    def __init__(self) -> None:
        self._email: str | None = None
        self._captcha_hit = False

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HungryrootOptionsFlow()

    # ---- shared ------------------------------------------------------------

    async def _check_session(self, client: HungryrootClient) -> str:
        """Confirm the session works and return the Hungryroot customer id."""
        customer = await client.get_customer()
        customer_id = customer.get("id") or customer.get("customer_id")
        if customer_id is None:
            raise HungryrootAuthError("No customer id in account response")
        return str(customer_id)

    async def _finish(self, client: HungryrootClient, customer_id: str) -> ConfigFlowResult:
        data = {CONF_COOKIE: client.cookie}
        if self._email:
            data[CONF_EMAIL] = self._email
        await self.async_set_unique_id(customer_id)
        if self.source in ("reauth", "reconfigure"):
            entry = (
                self._get_reauth_entry()
                if self.source == "reauth"
                else self._get_reconfigure_entry()
            )
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(entry, data_updates=data)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=self._email or "Hungryroot", data=data)

    # ---- entry points ------------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["login", "session"])

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._email = entry_data.get(CONF_EMAIL)
        return await self.async_step_reauth_menu()

    async def async_step_reauth_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(step_id="reauth_menu", menu_options=["login", "session"])

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._email = self._get_reconfigure_entry().data.get(CONF_EMAIL)
        return self.async_show_menu(step_id="reconfigure", menu_options=["login", "session"])

    # ---- email + password --------------------------------------------------

    async def async_step_login(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip()
            client = HungryrootClient(async_create_clientsession(self.hass))
            try:
                await client.login(self._email, user_input[CONF_PASSWORD])
                customer_id = await self._check_session(client)
            except HungryrootCaptchaRequired:
                self._captcha_hit = True
                return await self.async_step_session()
            except HungryrootAuthError:
                errors["base"] = "invalid_auth"
            except HungryrootError:
                _LOGGER.exception("Hungryroot login failed")
                errors["base"] = "cannot_connect"
            else:
                return await self._finish(client, customer_id)

        return self.async_show_form(
            step_id="login",
            data_schema=self.add_suggested_values_to_schema(
                LOGIN_SCHEMA, {CONF_EMAIL: self._email or ""}
            ),
            errors=errors,
            last_step=False,
        )

    # ---- paste session (captcha fallback) ----------------------------------

    async def async_step_session(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = HungryrootClient(
                async_create_clientsession(self.hass), user_input[CONF_COOKIE]
            )
            try:
                customer_id = await self._check_session(client)
            except HungryrootAuthError:
                errors["base"] = "invalid_session"
            except HungryrootError:
                _LOGGER.exception("Hungryroot session check failed")
                errors["base"] = "cannot_connect"
            else:
                return await self._finish(client, customer_id)

        return self.async_show_form(
            step_id="session",
            data_schema=SESSION_SCHEMA,
            errors=errors,
            description_placeholders={
                "reason": (
                    "Hungryroot asked for a captcha, so Home Assistant can't log in "
                    "with your password. Paste a session from your browser instead."
                    if self._captcha_hit
                    else "Paste a session from a browser where you're logged in."
                )
            },
        )


class HungryrootOptionsFlow(OptionsFlow):
    """Settings screen: how often to check."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_HOURS: int(user_input[CONF_SCAN_HOURS])}
            )
        current = self.config_entry.options.get(CONF_SCAN_HOURS, DEFAULT_SCAN_HOURS)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_HOURS, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_HOURS,
                            max=MAX_SCAN_HOURS,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="hours",
                        )
                    )
                }
            ),
        )
