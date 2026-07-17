export const DOC_TYPE_OPTIONS = [
  { value: 'competition', label: '공모전' },
  { value: 'government_support', label: '정부지원사업' },
  { value: 'startup', label: '사업계획서(스타트업)' },
]

export function docTypeLabel(value) {
  return DOC_TYPE_OPTIONS.find((opt) => opt.value === value)?.label || value
}
