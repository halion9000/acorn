'use client';

import { useState } from 'react';
import useSWR, { mutate } from 'swr';
import { EmptyState, EmptyStateIcons } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { authFetch } from '@/lib/auth-session';
import { failureDetail } from '@/lib/failure-detail';
import { NAV_CATALOG } from '@/components/layout/Sidebar';
import { RoleVisibilityPicker } from './RoleVisibilityPicker';
import { ROLE_PRESETS, presetPermissionIds } from './rolePresets';
import { SsoDefaultRoleCard } from './SsoDefaultRoleCard';

interface Permission {
  id: string;
  name: string;
  description: string | null;
  category: string | null;
}

interface Role {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  is_system: boolean;
  /** Sections ("section:Automation") and pages the role hides in the console. Absent from an older API. */
  hidden_nav?: string[];
  permissions: Permission[];
}

/** A role that ships with the product: fixed in code, listed here with exactly what it grants. */
interface BuiltinRole {
  key: string;
  label: string;
  description: string;
  permissions: string[];
}

/** What a copy of a built-in role starts with: nothing is saved until the person presses Create. */
interface Prefill {
  name: string;
  description: string;
  permissionNames: string[];
}

const fetcher = (url: string) =>
  authFetch(url).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  });

const CATEGORY_COLORS: Record<string, string> = {
  cases: 'bg-blue-500/20 text-blue-300',
  alerts: 'bg-red-500/20 text-red-300',
  playbooks: 'bg-purple-500/20 text-purple-300',
  detections: 'bg-orange-500/20 text-orange-300',
  connectors: 'bg-teal-500/20 text-teal-300',
  api_keys: 'bg-yellow-500/20 text-yellow-300',
  audit: 'bg-gray-500/20 text-gray-300',
  compliance: 'bg-green-500/20 text-green-300',
  admin: 'bg-pink-500/20 text-pink-300',
};

function PermissionBadge({ perm }: { perm: Permission }) {
  const cls = CATEGORY_COLORS[perm.category ?? ''] ?? 'bg-gray-500/20 text-gray-300';
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${cls}`} title={perm.description ?? ''}>
      {perm.name}
    </span>
  );
}

function RoleCard({ role, onEdit, onDelete }: { role: Role; onEdit: (r: Role) => void; onDelete: (r: Role) => void }) {
  return (
    <div className="rounded-xl border border-gray-800/60 bg-gray-900/60 p-5">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-base font-semibold text-gray-100">{role.name}</span>
            {role.is_system && (
              <span className="rounded bg-indigo-100 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-indigo-700">
                system
              </span>
            )}
          </div>
          {role.description && <p className="mt-0.5 text-sm text-gray-400">{role.description}</p>}
        </div>
        {!role.is_system && (
          <div className="flex shrink-0 gap-2">
            <button
              onClick={() => onEdit(role)}
              className="rounded px-2 py-1 text-xs text-gray-400 hover:bg-gray-800"
            >
              Edit
            </button>
            <button
              onClick={() => onDelete(role)}
              className="rounded px-2 py-1 text-xs text-red-400 hover:bg-red-900/30"
            >
              Delete
            </button>
          </div>
        )}
      </div>
      {(role.hidden_nav?.length ?? 0) > 0 && (
        <p className="mt-2 text-xs text-gray-500">
          Hides: {role.hidden_nav!.map((h) => (h.startsWith('section:') ? h.slice('section:'.length) : h)).join(', ')}
        </p>
      )}
      <div className="mt-3 flex flex-wrap gap-1.5">
        {role.permissions.length === 0 ? (
          <span className="text-xs text-gray-500 italic">No permissions assigned</span>
        ) : (
          role.permissions.map((p) => <PermissionBadge key={p.id} perm={p} />)
        )}
      </div>
    </div>
  );
}

const ACTION_ORDER = ['read', 'write', 'delete'];

/** A category's permissions in one fixed order: read, write, delete, then anything else (view, work...) by name. */
export function orderPermissions<T extends { name: string }>(perms: T[]): T[] {
  const action = (p: T) => p.name.split(':').pop() ?? p.name;
  const rank = (p: T) => {
    const i = ACTION_ORDER.indexOf(action(p));
    return i === -1 ? ACTION_ORDER.length : i;
  };
  return [...perms].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
}

/** The tick next to a category's name: ticked when all its permissions are, dashed when some are. */
function CategoryToggle({ label, ids, selected, onChange }: { label: string; ids: string[]; selected: Set<string>; onChange: (ids: string[], on: boolean) => void }) {
  const have = ids.filter((id) => selected.has(id)).length;
  const all = ids.length > 0 && have === ids.length;
  return (
    <label className="mb-1 flex cursor-pointer items-center gap-1.5">
      <input
        type="checkbox"
        aria-label={`Select all ${label} permissions`}
        checked={all}
        ref={(el) => {
          if (el) el.indeterminate = have > 0 && !all;
        }}
        onChange={() => onChange(ids, !all)}
        className="rounded border-gray-600 bg-gray-950 accent-indigo-500 text-indigo-500"
      />
      <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">{label}</span>
    </label>
  );
}

interface RoleFormProps {
  allPermissions: Permission[];
  initial?: Role;
  prefill?: Prefill;
  onClose: () => void;
}

function RoleForm({ allPermissions, initial, prefill, onClose }: RoleFormProps) {
  const [name, setName] = useState(initial?.name ?? prefill?.name ?? '');
  const [description, setDescription] = useState(initial?.description ?? prefill?.description ?? '');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    new Set(initial ? initial.permissions.map((p) => p.id) : prefill ? allPermissions.filter((p) => prefill.permissionNames.includes(p.name)).map((p) => p.id) : [])
  );
  // Permissions the built-in role grants that this list does not offer (so the copy cannot include them): said, not hidden.
  const leftOut = prefill ? prefill.permissionNames.filter((n) => !allPermissions.some((p) => p.name === n)) : [];
  const [hidden, setHidden] = useState<Set<string>>(new Set(initial?.hidden_nav ?? []));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const applyPreset = (key: string) => {
    const preset = ROLE_PRESETS.find((p) => p.key === key);
    if (!preset) return;
    setHidden(new Set(preset.hidden));
    setSelectedIds(new Set(presetPermissionIds(preset, allPermissions)));
    if (!name.trim()) setName(preset.label);
    if (!description.trim()) setDescription(preset.description);
  };

  const categories = Array.from(new Set(allPermissions.map((p) => p.category ?? 'other'))).sort();

  const toggle = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const setMany = (ids: string[], on: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      for (const id of ids) {
        if (on) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  };

  const save = async () => {
    if (!name.trim()) { setError('Name is required'); return; }
    setSaving(true);
    setError(null);
    try {
      const url = initial ? `/api/v1/rbac/roles/${initial.id}` : '/api/v1/rbac/roles';
      const method = initial ? 'PATCH' : 'POST';
      const res = await authFetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description: description || null, permission_ids: Array.from(selectedIds), hidden_nav: Array.from(hidden) }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail ?? 'Save failed');
      }
      await mutate('/api/v1/rbac/roles');
      onClose();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div role="dialog" aria-modal="true" aria-label={initial ? 'Edit role' : 'Create role'} className="w-full max-w-2xl rounded-2xl border border-gray-700 bg-gray-900 text-gray-100 shadow-2xl">
        <div className="flex items-center justify-between border-b border-gray-800 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-100">{initial ? 'Edit Role' : 'Create Role'}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-200" aria-label="Close">✕</button>
        </div>
        <div className="max-h-[70vh] space-y-4 overflow-y-auto px-6 py-4">
          {prefill && (
            <p className="rounded bg-indigo-500/10 px-3 py-2 text-sm text-indigo-200">
              Started from the built-in role <strong>{prefill.name.replace(/ \(copy\)$/, '')}</strong>. Change anything, then press Create; the built-in role itself stays as it is.
              {leftOut.length > 0 ? ` ${leftOut.length} permission(s) it grants are not offered here and were left out: ${leftOut.join(', ')}.` : ''}
            </p>
          )}
          {!initial && !prefill && (
            <div>
              <p className="mb-1 text-sm font-medium text-gray-200">Start from</p>
              <div className="flex flex-wrap gap-2">
                {ROLE_PRESETS.map((p) => (
                  <button
                    key={p.key}
                    type="button"
                    title={p.description}
                    onClick={() => applyPreset(p.key)}
                    className="rounded-full border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:border-indigo-500 hover:bg-indigo-500/10"
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <p className="mt-1 text-xs text-gray-400">Fills in the permissions and what is hidden. Nothing is saved until you press Create.</p>
            </div>
          )}
          {error && <p className="rounded bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</p>}
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-200">Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100 placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              placeholder="e.g. threat-hunter"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-200">Description</label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100 placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              placeholder="Optional description"
            />
          </div>
          <div>
            <label className="mb-2 block text-sm font-medium text-gray-200">
              Permissions ({selectedIds.size} selected)
            </label>
            <div className="max-h-64 overflow-y-auto space-y-3 rounded-lg border border-gray-700 p-3">
              {categories.map((cat) => (
                <div key={cat}>
                  <CategoryToggle label={cat} ids={allPermissions.filter((p) => (p.category ?? 'other') === cat).map((p) => p.id)} selected={selectedIds} onChange={setMany} />
                  <div className="flex flex-wrap gap-2 pl-6">
                    {orderPermissions(allPermissions.filter((p) => (p.category ?? 'other') === cat))
                      .map((perm) => (
                        <label key={perm.id} className="flex cursor-pointer items-center gap-1.5">
                          <input
                            type="checkbox"
                            checked={selectedIds.has(perm.id)}
                            onChange={() => toggle(perm.id)}
                            className="rounded border-gray-600 bg-gray-950 accent-indigo-500 text-indigo-500"
                          />
                          <span className="text-xs text-gray-200">{perm.name}</span>
                        </label>
                      ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-200">What people in this role see</label>
            <p className="mb-2 text-xs text-gray-400">Untick a section or a page to hide it from the sidebar and stop its address opening. This is about what is shown; the permissions above are what is enforced.</p>
            <RoleVisibilityPicker catalog={NAV_CATALOG} hidden={hidden} onChange={setHidden} />
          </div>
        </div>
        <div className="flex justify-end gap-3 border-t border-gray-800 px-6 py-4">
          <button onClick={onClose} className="rounded-lg px-4 py-2 text-sm text-gray-300 hover:bg-gray-800">
            Cancel
          </button>
          <button
            onClick={save}
            disabled={saving}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {saving ? 'Saving…' : initial ? 'Update' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}

export function RBACView() {
  const { data: roles, error: rolesError, isLoading: rolesLoading } = useSWR<Role[]>('/api/v1/rbac/roles', fetcher);
  const { data: permissions, isLoading: permsLoading } = useSWR<Permission[]>('/api/v1/rbac/permissions', fetcher);

  const { data: builtins } = useSWR<BuiltinRole[]>('/api/v1/rbac/builtin-roles', fetcher);
  const [showCreate, setShowCreate] = useState(false);
  const [prefill, setPrefill] = useState<Prefill | null>(null);
  const [openBuiltin, setOpenBuiltin] = useState<string | null>(null);
  const [editingRole, setEditingRole] = useState<Role | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const handleDelete = async (role: Role) => {
    if (!confirm(`Delete role "${role.name}"?`)) return;
    setDeleteError(null);
    try {
      // The response used to be ignored, so a refused delete (e.g. a system role, or no permission) looked like nothing had happened.
      const res = await authFetch(`/api/v1/rbac/roles/${role.id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(await failureDetail(res));
    } catch (err) {
      setDeleteError(`Could not delete "${role.name}": ${err instanceof Error ? err.message : 'the request failed'}`);
    }
    mutate('/api/v1/rbac/roles');
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-100">Roles & Permissions</h2>
          <p className="mt-0.5 text-sm text-gray-500">Manage access control for your organization.</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          + New Role
        </button>
      </div>

      {deleteError && (
        <div role="alert" className="rounded-md border border-red-500/30 bg-red-500/5 px-4 py-2 text-xs text-red-200">
          {deleteError}
        </div>
      )}
      {/* No sample roles exist: the old banner said "showing demo roles", which was never true. */}
      {rolesError && !roles && (
        <ErrorState
          title="Couldn't load roles"
          description="The access-control service didn't respond."
          error={rolesError}
          onRetry={() => void mutate('/api/v1/rbac/roles')}
        />
      )}
      {rolesError && roles && (
        <div role="alert" className="rounded-md border border-amber-500/30 bg-amber-500/5 px-4 py-2 text-xs text-amber-200">
          Couldn&rsquo;t refresh roles; showing what was last loaded.
        </div>
      )}

      {!roles && !rolesError && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-32 animate-pulse rounded-xl bg-gray-800/60" />
          ))}
        </div>
      )}

      {roles && roles.length === 0 && (
        <EmptyState
          icon={EmptyStateIcons.shield}
          title="No roles defined yet"
          description="Create your first role to start managing access control for your organization."
          action={
            <button
              type="button"
              onClick={() => setShowCreate(true)}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 transition-colors"
            >
              + New Role
            </button>
          }
        />
      )}

      <SsoDefaultRoleCard customRoles={(roles ?? []).filter((r) => !r.is_system).map((r) => ({ id: r.id, name: r.name }))} />

      {builtins && builtins.length > 0 && (
        <section aria-labelledby="builtin-roles-heading" className="space-y-3">
          <div>
            <h3 id="builtin-roles-heading" className="text-sm font-semibold text-gray-200">Built-in roles</h3>
            <p className="text-xs text-gray-500">These come with the product and are the same for every workspace, so they cannot be edited. To change one, make a copy: it becomes a custom role you can edit freely, and you can give it to people instead.</p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {builtins.map((b) => (
              <div key={b.key} className="rounded-xl border border-gray-800/60 bg-gray-900/60 p-5">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-base font-semibold text-gray-100">{b.label}</span>
                      <span className="rounded bg-gray-700 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-gray-200">built-in</span>
                    </div>
                    <p className="mt-0.5 text-sm text-gray-400">{b.description}</p>
                  </div>
                  <button
                    type="button"
                    aria-label={`Copy ${b.label} to edit`}
                    onClick={() => setPrefill({ name: `${b.label} (copy)`, description: b.description, permissionNames: b.permissions })}
                    className="shrink-0 rounded px-2 py-1 text-xs text-gray-300 hover:bg-gray-800"
                  >
                    Copy to edit
                  </button>
                </div>
                <button
                  type="button"
                  aria-expanded={openBuiltin === b.key}
                  onClick={() => setOpenBuiltin(openBuiltin === b.key ? null : b.key)}
                  className="mt-3 text-xs text-indigo-300 hover:underline"
                >
                  {openBuiltin === b.key ? 'Hide' : 'Show'} the {b.permissions.length} permissions
                </button>
                {openBuiltin === b.key ? (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {b.permissions.map((n) => (
                      <span key={n} className="inline-block rounded bg-gray-500/20 px-2 py-0.5 text-xs font-medium text-gray-300">{n}</span>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      )}

      {roles && roles.length > 0 && (
        <h3 className="text-sm font-semibold text-gray-200">Your roles</h3>
      )}
      {roles && roles.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {roles.map((role) => (
            <RoleCard
              key={role.id}
              role={role}
              onEdit={(r) => setEditingRole(r)}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}

      {(showCreate || editingRole || prefill) && permissions && (
        <RoleForm
          allPermissions={permissions}
          initial={editingRole ?? undefined}
          prefill={prefill ?? undefined}
          onClose={() => {
            setShowCreate(false);
            setEditingRole(null);
            setPrefill(null);
          }}
        />
      )}
    </div>
  );
}
