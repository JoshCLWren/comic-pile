export interface UserResponse {
  id: number;
  username: string;
  email: string | null;
  is_admin: boolean;
}

/** Claims retained after a JWT has passed the access-token boundary checks. */
export interface VerifiedAccessTokenClaims {
  sub: string;
  jti: string;
  type: 'access';
  exp: number;
  pc?: number;
}
