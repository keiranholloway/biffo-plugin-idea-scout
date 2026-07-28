import type { BuildType } from '../lib/api'

interface Props {
  types: readonly BuildType[]
  busy: boolean
  onEdit: (type: BuildType) => void
  onToggleActive: (type: BuildType) => void
}

/**
 * The categories, in the order a founder sees them.
 *
 * `active` is nullable because the generated migration DDL does not apply
 * declared defaults — treat null as false, the same reading the service uses.
 */
export function BuildTypeList({ types, busy, onEdit, onToggleActive }: Props) {
  if (types.length === 0) {
    // An empty list is a real state with a real consequence: the founder's run
    // form has nothing to offer and cannot start a scout. Say that, rather than
    // rendering an empty table that looks like a loading glitch.
    return <p className="muted">No build types yet — a founder cannot start a scout until one exists.</p>
  }

  return (
    <table className="build-types">
      <thead>
        <tr>
          <th>Label</th>
          <th>Key</th>
          <th>Order</th>
          <th>Status</th>
          <th>
            <span className="sr-only">Actions</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {types.map((type) => {
          const active = type.active ?? false
          return (
            <tr key={type.id} className={active ? undefined : 'inactive'}>
              <td>
                <span className="type-label">{type.label}</span>
                {type.description != null && type.description !== '' && (
                  <span className="type-description">{type.description}</span>
                )}
              </td>
              <td>
                <code>{type.key}</code>
              </td>
              <td>{type.sort_order ?? '—'}</td>
              <td>
                <span className="type-status" data-active={active ? 'yes' : 'no'}>
                  {active ? 'Active' : 'Hidden'}
                </span>
              </td>
              <td className="type-actions">
                <button type="button" disabled={busy} onClick={() => onEdit(type)}>
                  Edit
                </button>
                <button type="button" disabled={busy} onClick={() => onToggleActive(type)}>
                  {active ? 'Hide' : 'Show'}
                </button>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
