import { create } from "zustand"
import { persist } from "zustand/middleware"
import type { User } from "@/lib/schemas"

interface AuthState {
  accessToken: string | null
  user: User | null
  setAuth: (token: string, user: User) => void
  setAccessToken: (token: string) => void
  logout: () => void
  isAuthenticated: boolean
}

export interface AuthStoreApi {
  getState: () => AuthState
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      user: null,
      isAuthenticated: false,
      setAuth: (token, user) =>
        set({ accessToken: token, user, isAuthenticated: true }),
      setAccessToken: (token) =>
        set({ accessToken: token, isAuthenticated: true }),
      logout: () =>
        set({ accessToken: null, user: null, isAuthenticated: false }),
    }),
    {
      name: "auth-storage",
      // persist user + auth flag; accessToken reacquired via refresh cookie on reload
      partialize: (state) => ({ user: state.user, isAuthenticated: state.isAuthenticated }),
    }
  )
)
