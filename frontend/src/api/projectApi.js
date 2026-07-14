import { mockProjects } from '../mocks/projects'

export async function getProjects() {
  await new Promise((resolve) => setTimeout(resolve, 300))
  return mockProjects
}
