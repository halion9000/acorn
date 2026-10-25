"use client";

/**
 * What one tool says about the client as plain checks CORE reads once a day and sends for a client that is mapped to that tool: ThreatMate (security score, patching, end-of-life software) and
 * Liongard (disk encryption, EDR coverage, e-mail domain records, stale licensed users). Nothing is shown for a client with none (not mapped, or nothing sent yet).
 */

export interface PostureCheck {
  key: string;
  status: 'met' | 'partly' | 'not_met' | string;
  evidence: string;
}

const TITLE: Record<string, string> = {
  threatmate_security_score: 'Security score',
  threatmate_patching: 'Patching',
  threatmate_end_of_life: 'End-of-life software',
  itglue_domain_expiry: 'Domain names',
  itglue_certificate_expiry: 'SSL certificates',
  threatmate_external_exposure: 'External exposure',
  threatmate_dmarc: 'DMARC and SPF',
  threatmate_hardening: 'Endpoint hardening',
  threatmate_cyber_insurance: 'Cyber insurance baseline',
  threatmate_frameworks: 'Compliance frameworks',
  liongard_disk_encryption: 'Disk encryption (BitLocker)',
  liongard_edr_coverage: 'EDR coverage',
  liongard_email_domain_records: 'E-mail domain records',
  liongard_stale_licensed_users: 'Stale licensed users',
  liongard_iis_certificates: 'Web server certificates (IIS)',
  liongard_datto_bcdr: 'Datto backup appliance',
  liongard_ad_bad_logins: 'Active Directory failed sign-ins',
  fieldeffect_account_risk: 'Account risk',
  fieldeffect_device_risk: 'Machine risk',
  cipp_inactive_accounts: 'Unused accounts',
  cipp_subscriptions: 'Microsoft 365 subscriptions',
  cipp_unused_licences: 'Unused licences',
  ninjaone_unsupported_os: 'Windows support status',
  ninjaone_antivirus: 'Antivirus',
  ninjaone_patching: 'Windows updates',
  halopsa_agreement: 'Support agreement',
  meraki_licence: 'Meraki licence',
  meraki_admin_2fa: 'Meraki administrators',
  meraki_wan: 'Internet connections',
  slide_alerts: 'Backup alerts',
  slide_appliance: 'Backup appliance',
  slide_verification: 'Backup test boots',
  autoelevate_enforcing: 'Admin-rights protection',
  autoelevate_requests: 'Elevation requests',
  huntress_protection: 'Endpoint protection health',
  huntress_quiet_agents: 'Agents gone quiet',
  huntress_extra_coverage: 'Huntress identity and SIEM',
  dnsfilter_threat_blocking: 'Threat blocking (DNS)',
  dnsfilter_org_mfa: 'DNS filtering sign-in',
  dnsfilter_traffic: 'DNS filtering traffic',
  datto_saas_seats: 'Mailbox backup coverage',
  threatmate_ai_tools: 'AI tools in use',
  threatmate_pentest: 'Vulnerability scans',
  threatmate_m365_controls: 'Microsoft 365 identity controls',
};

const STATUS: Record<string, { text: string; className: string }> = {
  met: { text: 'Good', className: 'border-emerald-500/40 text-emerald-300' },
  partly: { text: 'Needs attention', className: 'border-amber-500/40 text-amber-300' },
  not_met: { text: 'Problem', className: 'border-red-500/40 text-red-300' },
};

export function ToolChecks({ tool, label, checks, refreshedAt }: { tool: string; label: string; checks: PostureCheck[]; refreshedAt?: string | null }) {
  if (checks.length === 0) return null;
  return (
    <section data-testid={`${tool}-checks`}>
      <h3 className="mb-2 text-sm uppercase text-slate-500">
        {label}{refreshedAt ? <span className="ml-2 text-xs normal-case text-slate-600">as of {new Date(refreshedAt).toLocaleDateString()}</span> : null}
      </h3>
      <div className="grid gap-2 md:grid-cols-3">
        {checks.map((c) => {
          const st = STATUS[c.status] ?? STATUS.partly;
          return (
            <div key={c.key} className="rounded border border-slate-800 p-2" data-testid={`check-${c.key}`}>
              <div className="text-xs uppercase text-slate-500">{TITLE[c.key] ?? c.key.replace(/^(threatmate|liongard|itglue|fieldeffect|cipp|ninjaone|halopsa|meraki|slide|autoelevate|huntress|dnsfilter|datto)_/, '').replace(/_/g, ' ')}</div>
              <span className={`mt-1 inline-block rounded border px-1.5 py-0.5 text-[11px] ${st.className}`}>{st.text}</span>
              <div className="mt-1 text-xs text-slate-400">{c.evidence}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
