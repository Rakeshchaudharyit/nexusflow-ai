import { NextResponse, type NextRequest } from "next/server";
import { PATH_HEADER } from "@/lib/return-path";

// Server layouts cannot see the requested URL; forward it so a signed-out visitor
// can be returned to the same workspace page after signing in.
export function proxy(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.set(PATH_HEADER, request.nextUrl.pathname + request.nextUrl.search);
  return NextResponse.next({ request: { headers } });
}

export const config = { matcher: "/app/:path*" };
