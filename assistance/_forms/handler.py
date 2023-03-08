# Copyright (C) 2023 Assistance.Chat contributors

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json

from assistance._types import Email
from assistance._config import (
    load_form_config,
    get_form_entries,
    get_complete_form_progression_keys,
    FormItem,
    set_progression_key,
    save_form_entries,
)
from assistance._email.thread import get_email_thread

from .build import walk_and_build_form_fields
from .progression import get_current_stage_and_task
from .confirmation import confirming_form_items

from .collect import collect_form_items
from .ready import check_if_user_is_ready_to_continue


async def handle_enrolment_email(form_name: str, email: Email):
    user_email = email["user_email"]
    email_thread = get_email_thread(email)

    cfg = await load_form_config(form_name)
    form_entries = await get_form_entries(form_name, user_email)

    fields_that_need_confirmation = set()
    for key, item in form_entries.items():
        if item["confirmed"]:
            continue

        fields_that_need_confirmation.add(key)

    if fields_that_need_confirmation:
        confirmation_form_fields_text = walk_and_build_form_fields(
            cfg["field"], allow=fields_that_need_confirmation
        )

        form_fields_with_updated_confirmation = await confirming_form_items(
            email=email, confirmation_form_fields_text=confirmation_form_fields_text
        )

        for key, item in form_fields_with_updated_confirmation.items():
            if key not in form_entries:
                continue

            # We don't want to overwrite a previous confirmation
            if form_entries[key]["value"] == item["value"] and item["confirmed"]:
                form_entries[key]["confirmed"] = True

    remaining_form_fields_text = walk_and_build_form_fields(
        cfg["field"], ignore=set(form_entries.keys())
    )

    new_collected_items = await collect_form_items(
        email=email, remaining_form_fields_text=remaining_form_fields_text
    )
    new_form_entries = {
        key: FormItem(value=value, confirmed=False)
        for key, value in new_collected_items.items()
    }

    for key, item in new_form_entries.items():
        if key in form_entries:
            if item["value"] == form_entries[key]["value"]:
                continue

        form_entries[key] = item

    fields_that_still_need_confirmation = set()
    for key, item in form_entries.items():
        if item["confirmed"]:
            continue

        fields_that_still_need_confirmation.add(key)

    confirmation_still_needed_field_descriptions = walk_and_build_form_fields(
        cfg["field"], allow=fields_that_still_need_confirmation
    )
    confirmation_field_values = {}
    for key, item in form_entries.items():
        if key not in fields_that_still_need_confirmation:
            continue

        confirmation_field_values[key] = item["value"]

    confirmation_field_values_text = json.dumps(confirmation_field_values, indent=2)

    while True:
        form_progression = await get_complete_form_progression_keys(
            form_name, user_email
        )
        stage, task, fields_for_stage_completion = get_current_stage_and_task(
            cfg["progression"], form_progression
        )

        if fields_for_stage_completion is None or stage is None:
            break

        if len(set(fields_for_stage_completion).difference(form_entries)) == 0:
            await set_progression_key(form_name, user_email, stage)
            continue

    if stage is None:
        stage = cfg["progression"][-1]["key"]
        task = cfg["progression"][-1]["task"]

    if stage == cfg["progression"][0]["key"]:
        ready_to_continue = True
    else:
        ready_to_continue = await check_if_user_is_ready_to_continue(email)

    if not ready_to_continue:
        task = "- Be helpful and responsive to the user's queries.\n- Ask the user whether or not they are ready to continue with the questions for the form."

    updated_remaining_form_fields_text = walk_and_build_form_fields(
        cfg["field"], ignore=set(form_entries.keys())
    )

    await save_form_entries(form_name, user_email, form_entries)

    # TODO: Write the email response

    if fields_for_stage_completion is None:
        await set_progression_key(form_name, user_email, stage)
