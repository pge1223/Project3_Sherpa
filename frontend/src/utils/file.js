export const ACCEPTED_DOCUMENT_EXTENSIONS = ['.pdf', '.docx', '.pptx']

export function isAcceptedDocument(file) {
  const name = file.name.toLowerCase()
  return ACCEPTED_DOCUMENT_EXTENSIONS.some((ext) => name.endsWith(ext))
}

export function formatFileSize(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}
