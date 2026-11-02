'use client';

import { useEffect, useState } from 'react';

import { apiErrorDetail, tenantsApi, type CustomRole, type TenantUser } from '@/lib/api';
import { Field, inputClass } from './panel-parts';

/** The roles an administrator can hand out from here. The server decides who may grant which (nobody can give more than their own role) and says so if the answer is no. */
export const MEMBER_ROLES: { value: string; label: string; hint: string }[] = [
  { value: 'viewer', label: 'Viewer', hint: 'Can look, cannot change anything.' },
  { value: 'soc_analyst', label: 'SOC analyst', hint: 'Works alerts and cases.' },
  { value: 'threat_hunter', label: 'Threat hunter', hint: 'Analyst who also runs hunts and queries.' },
  { value: 'soc_lead', label: 'SOC lead', hint: 'Analyst who also manages the team and rules.' },
  { value: 'tenant_admin', label: 'Administrator', hint: 'Manages the workspace, its members and settings.' },
];

/** A role this workspace made itself is chosen as `custom:<id>`; the person is then added as a Viewer (the lowest built-in role) holding that custom role, so what they can do is what the custom role grants. */
export const CUSTOM_PREFIX = 'custom:';

export const MIN_PASSWORD_LENGTH = 12;
const ACCOUNT_NAME = /^[a-z0-9][a-z0-9._-]{1,30}[a-z0-9]$/;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export interface MemberFields {
  accountName: string;
  displayName: string;
  email: string;
  role: string;
  password: string;
}

/** What is wrong with the form, field by field (empty when it can be sent). The server checks all of it again. */
export function memberFormProblems(f: MemberFields): Partial<Record<keyof MemberFields, string>> {
  const out: Partial<Record<keyof MemberFields, string>> = {};
  const name = f.accountName.trim().toLowerCase();
  if (!name) out.accountName = 'Choose the name this person signs in with.';
  else if (!ACCOUNT_NAME.test(name)) out.accountName = "3 to 32 characters: lower-case letters, digits, '.', '_' or '-', starting and ending with a letter or digit.";
  if (f.email.trim() && !EMAIL.test(f.email.trim())) out.email = 'That does not look like an email address.';
  if (!MEMBER_ROLES.some((r) => r.value === f.role) && !f.role.startsWith(CUSTOM_PREFIX)) out.role = 'Choose a role.';
  if (f.password.length < MIN_PASSWORD_LENGTH) out.password = `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  return out;
}

const ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789';

/** A random password of letters and digits (no look-alike characters), from the browser's secure random source. */
export function generatePassword(length = 20, random: (n: number) => Uint32Array = (n) => crypto.getRandomValues(new Uint32Array(n))): string {
  const limit = Math.floor(0x100000000 / ALPHABET.length) * ALPHABET.length; // no bias toward the first letters
  let out = '';
  while (out.length < length) {
    for (const value of random(length * 2)) {
      if (value < limit && out.length < length) out += ALPHABET[value % ALPHABET.length];
    }
  }
  return out;
}

/** The form that adds a person to this workspace. The person signs in with the account name and the password set here. */
export function AddMemberForm({ onCreated, onCancel }: { onCreated: (user: TenantUser) => void; onCancel: () => void }) {
  const [fields, setFields] = useState<MemberFields>({ accountName: '', displayName: '', email: '', role: 'soc_analyst', password: '' });
  const [showPassword, setShowPassword] = useState(false);
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [added, setAdded] = useState<{ user: TenantUser; password: string } | null>(null);
  const [customRoles, setCustomRoles] = useState<CustomRole[]>([]);
  useEffect(() => {
    // Custom roles are an extra: if the list cannot be read (no permission, an older server) the built-in roles still work.
    let live = true;
    void (async () => {
      try {
        const roles = await tenantsApi.customRoles();
        if (live) setCustomRoles(roles);
      } catch {
        /* built-in roles only */
      }
    })();
    return () => {
      live = false;
    };
  }, []);
  const problems = memberFormProblems(fields);
  const set = <K extends keyof MemberFields>(key: K, value: MemberFields[K]) => setFields((f) => ({ ...f, [key]: value }));

  const submit = async () => {
    setTried(true);
    setError(null);
    if (Object.keys(problems).length > 0) return;
    setBusy(true);
    try {
      const user = await tenantsApi.createUser({
        account_name: fields.accountName.trim().toLowerCase(),
        username: fields.displayName.trim() || undefined,
        email: fields.email.trim() || undefined,
        password: fields.password,
        ...(fields.role.startsWith(CUSTOM_PREFIX) ? { role: 'viewer', custom_role_ids: [fields.role.slice(CUSTOM_PREFIX.length)] } : { role: fields.role }),
      });
      setAdded({ user, password: fields.password });
      onCreated(user);
    } catch (err) {
      setError(apiErrorDetail(err) ?? 'The member could not be added. Try again.');
    } finally {
      setBusy(false);
    }
  };

  if (added) {
    return (
      <div role="status" data-testid="member-added" className="mt-3 space-y-3 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4 text-sm">
        <p className="font-medium text-emerald-200">Added {added.user.username || added.user.account_name}.</p>
        <p className="text-gray-300">
          They sign in with the account name <span className="font-mono text-gray-100">{added.user.account_name}</span> and this password. Give it to them privately: it is not shown again.
        </p>
        <p className="rounded-md border border-gray-700 bg-gray-950 px-3 py-2 font-mono text-gray-100 select-all" data-testid="member-password">{added.password}</p>
        <p className="text-xs text-gray-500">There is no page yet where a person changes their own password, so keep a copy until they have signed in.</p>
        <button type="button" onClick={onCancel} className="rounded-lg border border-gray-700 px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-800">
          Done
        </button>
      </div>
    );
  }

  const shown = (key: keyof MemberFields) => (tried ? problems[key] : undefined);
  return (
    <form
      aria-label="Add a member"
      className="mt-3 space-y-4 rounded-lg border border-gray-800 bg-gray-950/40 p-4"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Account name" hint="What they sign in with. Lower-case letters, digits, '.', '_' or '-'.">
          <input className={inputClass()} value={fields.accountName} onChange={(e) => set('accountName', e.target.value)} autoComplete="off" placeholder="jane.doe" aria-invalid={!!shown('accountName')} />
          {shown('accountName') ? <span role="alert" className="text-xs text-red-300">{shown('accountName')}</span> : null}
        </Field>
        <Field label="Display name" hint="Optional. Shown in cases and audit.">
          <input className={inputClass()} value={fields.displayName} onChange={(e) => set('displayName', e.target.value)} autoComplete="off" placeholder="Jane Doe" />
        </Field>
        <Field label="Email" hint="Optional contact address. It is not needed to sign in.">
          <input type="email" className={inputClass()} value={fields.email} onChange={(e) => set('email', e.target.value)} autoComplete="off" placeholder="jane@example.com" aria-invalid={!!shown('email')} />
          {shown('email') ? <span role="alert" className="text-xs text-red-300">{shown('email')}</span> : null}
        </Field>
        <Field label="Role" hint={fields.role.startsWith(CUSTOM_PREFIX) ? customRoles.find((r) => CUSTOM_PREFIX + r.id === fields.role)?.description || 'A role your workspace made. They also hold the Viewer role.' : MEMBER_ROLES.find((r) => r.value === fields.role)?.hint}>
          <select className={inputClass()} value={fields.role} onChange={(e) => set('role', e.target.value)}>
            <optgroup label="Built-in roles">
              {MEMBER_ROLES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </optgroup>
            {customRoles.length > 0 ? (
              <optgroup label="Your custom roles">
                {customRoles.map((r) => (
                  <option key={r.id} value={CUSTOM_PREFIX + r.id}>
                    {r.name}
                  </option>
                ))}
              </optgroup>
            ) : null}
          </select>
        </Field>
      </div>
      <Field label="Starting password" hint={`At least ${MIN_PASSWORD_LENGTH} characters. Press Generate for a strong one.`}>
        <div className="flex gap-2">
          <input
            type={showPassword ? 'text' : 'password'}
            className={inputClass()}
            value={fields.password}
            onChange={(e) => set('password', e.target.value)}
            autoComplete="new-password"
            aria-invalid={!!shown('password')}
          />
          <button type="button" onClick={() => setShowPassword((v) => !v)} className="shrink-0 rounded-lg border border-gray-700 px-3 text-xs text-gray-200 hover:bg-gray-800">
            {showPassword ? 'Hide' : 'Show'}
          </button>
          <button
            type="button"
            onClick={() => {
              set('password', generatePassword());
              setShowPassword(true);
            }}
            className="shrink-0 rounded-lg border border-gray-700 px-3 text-xs text-gray-200 hover:bg-gray-800"
          >
            Generate
          </button>
        </div>
        {shown('password') ? <span role="alert" className="text-xs text-red-300">{shown('password')}</span> : null}
      </Field>
      {error ? (
        <p role="alert" data-testid="member-error" className="text-sm text-red-300">
          {error}
        </p>
      ) : null}
      <div className="flex gap-2">
        <button type="submit" disabled={busy} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50">
          {busy ? 'Adding…' : 'Add member'}
        </button>
        <button type="button" onClick={onCancel} className="rounded-lg border border-gray-700 px-4 py-2 text-sm text-gray-200 hover:bg-gray-800">
          Cancel
        </button>
      </div>
    </form>
  );
}
