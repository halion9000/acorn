"""Which client a domain belongs to, from the e-mail addresses of the people A.C.O.R.N holds for each client.

Some tools file a client's public domain under the MSP itself (ThreatMate's external scan of ``childrenandfamilies.org`` sits in the MSP's own segment), so an alert about
``webdisk.childrenandfamilies.org`` arrives tied to the MSP. The people of that client use ``@childrenandfamilies.org``, so the domain points at one client. Keep the rule in step with
services/fusion/app/services/alert_sink.py (which routes new alerts the same way).

A domain belongs to a client only when ALL hold: at least ``MIN_PEOPLE`` of its enabled, non-guest people use it (one contractor's address proves nothing), and no other client of the same MSP
has that many. The MSP's own domain therefore belongs to nobody, and an ambiguous one is left where it is.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import text

MIN_PEOPLE = 2

_SECOND_LEVEL = frozenset({"co", "com", "org", "net", "gov", "edu", "ac"})
_HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")

_OWNERS_SQL = """
SELECT lower(split_part(u.upn, '@', 2)) AS domain, u.tenant_id AS tenant_id, count(*) AS people
FROM identity_mfa_users u
JOIN tenants t ON t.id = u.tenant_id AND t.parent_tenant_id = :parent
WHERE position('@' in u.upn) > 0 AND u.enabled AND lower(coalesce(u.user_type, 'member')) <> 'guest'
GROUP BY 1, 2
HAVING count(*) >= :min_people
"""


def registrable_domain(name: object) -> str | None:
    """The domain a host name or e-mail address belongs to (``mail.example.org`` and ``a@example.org`` both give ``example.org``; ``www.example.co.uk`` gives ``example.co.uk``). None for anything that is not one."""
    text_ = str(name or "").strip().lower().rstrip(".")
    if "@" in text_:
        text_ = text_.rsplit("@", 1)[1]
    if not _HOST.match(text_):
        return None
    labels = text_.split(".")
    if not labels[-1][:1].isalpha():  # a top-level domain starts with a letter, so an IP address is not a domain
        return None
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


async def domain_owners(db: Any, parent_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """Every domain that points at exactly one client of this MSP, as ``domain -> client tenant``. ``*.onmicrosoft.com`` is never a client's own domain."""
    rows = (await db.execute(text(_OWNERS_SQL), {"parent": parent_id, "min_people": MIN_PEOPLE})).all()
    holders: dict[str, set[uuid.UUID]] = {}
    for domain, tenant_id, _people in rows:
        if domain and not domain.endswith("onmicrosoft.com"):
            holders.setdefault(domain, set()).add(tenant_id)
    return {d: next(iter(ts)) for d, ts in holders.items() if len(ts) == 1}
