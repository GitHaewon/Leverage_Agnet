import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from "axios"

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1"

// Lazy import to break circular dependency: api → authStore → api
function getAuthStore() {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return require("@/store/auth").useAuthStore as import("@/store/auth").AuthStoreApi
}

function createApiClient(): AxiosInstance {
  const instance = axios.create({
    baseURL: API_BASE_URL,
    withCredentials: true,
    headers: { "Content-Type": "application/json" },
  })

  instance.interceptors.request.use((config) => {
    const token = getAuthStore().getState().accessToken
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  })

  instance.interceptors.response.use(
    (response) => response,
    async (error: unknown) => {
      if (!axios.isAxiosError(error)) return Promise.reject(error)

      const originalRequest = error.config as InternalAxiosRequestConfig & {
        _retry?: boolean
      }

      if (error.response?.status === 401 && !originalRequest._retry) {
        originalRequest._retry = true
        try {
          const { data } = await axios.post(
            `${API_BASE_URL}/auth/refresh`,
            {},
            { withCredentials: true }
          )
          const newToken = (data as { data: { access_token: string } }).data
            .access_token
          getAuthStore().getState().setAccessToken(newToken)
          originalRequest.headers.Authorization = `Bearer ${newToken}`
          return instance(originalRequest)
        } catch {
          getAuthStore().getState().logout()
          if (typeof window !== "undefined") {
            window.location.href = "/login"
          }
        }
      }

      return Promise.reject(error)
    }
  )

  return instance
}

export const api = createApiClient()
