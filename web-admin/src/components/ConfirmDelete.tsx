interface ConfirmDeleteProps {
  /** What is being deleted, for the prompt: "Delete this agent?" */
  prompt: string
  disabled?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/** The kit's in-page confirm; replaces the native window.confirm dialog. */
export function ConfirmDelete({ prompt, disabled, onConfirm, onCancel }: ConfirmDeleteProps) {
  return (
    <span className="biffo-confirm" role="group" aria-label={prompt}>
      <span className="biffo-confirm__prompt">{prompt} This cannot be undone.</span>
      <button
        type="button"
        className="biffo-btn-delete biffo-confirm__yes"
        onClick={onConfirm}
        disabled={disabled}
      >
        Delete
      </button>
      <button type="button" className="biffo-confirm__no" onClick={onCancel} disabled={disabled}>
        Cancel
      </button>
    </span>
  )
}
