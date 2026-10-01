import NextAuth, { type NextAuthConfig } from "next-auth"
import Credentials from "next-auth/providers/credentials"
import GitHub from "next-auth/providers/github"

const development = process.env.NODE_ENV === "development"

function providers(): NextAuthConfig["providers"] {
  if (process.env.AUTH_GITHUB_ID) {
    return [GitHub]
  }
  if (development) {
    return [
      Credentials({
        id: "local",
        name: "Local admin",
        credentials: {},
        authorize: () => ({ id: "local", name: "Local admin" }),
      }),
    ]
  }
  return []
}

function allowed(provider: unknown, accountId: unknown): boolean {
  if (provider === "local") {
    return development
  }
  const admin = process.env.AHQ_ADMIN_GITHUB_ID?.trim()
  return provider === "github" && Boolean(admin) && accountId === admin
}

export const signInProvider: "github" | "local" | null = process.env
  .AUTH_GITHUB_ID
  ? "github"
  : development
    ? "local"
    : null

export const { handlers, auth, signIn, signOut } = NextAuth({
  basePath: "/auth",
  providers: providers(),
  secret:
    process.env.AUTH_SECRET ??
    (development ? "local-development-only" : undefined),
  trustHost: true,
  session: { strategy: "jwt" },
  callbacks: {
    signIn({ account }) {
      return allowed(account?.provider, account?.providerAccountId)
    },
    jwt({ token, account, profile }) {
      if (account) {
        token.provider = account.provider
        token.accountId = account.providerAccountId
      }
      if (typeof profile?.login === "string") {
        token.login = profile.login
      }
      return allowed(token.provider, token.accountId) ? token : null
    },
    session({ session, token }) {
      session.login = typeof token.login === "string" ? token.login : "local"
      return session
    },
  },
})

export async function currentSession() {
  if (!process.env.AUTH_SECRET && !development) {
    return null
  }
  try {
    return await auth()
  } catch {
    return null
  }
}

export async function isAdmin(): Promise<boolean> {
  return (await currentSession()) !== null
}
