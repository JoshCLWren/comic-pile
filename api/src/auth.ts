import type { Request, Response } from 'express';
import { getAuthenticatedUser } from './authService.js';

interface ErrorResponse {
  error: string;
}

function errnoCode(error: Error): string | undefined {
  if ('code' in error) {
    // SAFETY: Node/system errors may carry a string errno code; we read it as unknown and validate its class tag before returning.
    const code = (error as { code?: unknown }).code;
    if (Object.prototype.toString.call(code) === '[object String]') {
      // SAFETY: class-tag check above establishes this is a string primitive/object at runtime.
      return code as string;
    }
  }
  return undefined;
}

/** Map HTTP input and authentication outcomes at the transport boundary. */
export default async function authMeHandler(req: Request, res: Response): Promise<void> {
  try {
    res.json(await getAuthenticatedUser(req.headers.authorization));
  } catch (error) {
    // Do not log untrusted token or database error messages.

    // Map specific error types to appropriate HTTP status codes
    if (error instanceof Error) {
      const message = error.message;

      if (message === 'Missing or invalid authorization header') {
        // SAFETY: literal payload matches ErrorResponse contract for this 401 case.
        res.status(401).json({ error: 'Missing or invalid authorization header' } as ErrorResponse);
        return;
      }
      if (message === 'Token has been revoked' || message.includes('Token has been revoked')) {
        // SAFETY: literal payload matches ErrorResponse contract for this 401 case.
        res.status(401).json({ error: 'Token has been revoked' } as ErrorResponse);
        return;
      }
      if (message === 'User not found' || message.includes('User not found')) {
        // SAFETY: literal payload matches ErrorResponse contract for this 401 case.
        res.status(401).json({ error: 'User not found' } as ErrorResponse);
        return;
      }
      if (message === 'Password changed; please sign in again.' || message.includes('Password changed')) {
        // SAFETY: literal payload matches ErrorResponse contract for this 401 case.
        res.status(401).json({ error: 'Password changed; please sign in again.' } as ErrorResponse);
        return;
      }
      if (message.startsWith('Token verification failed:')) {
        if (message.includes('jwt expired') || message.includes('Invalid or expired token')) {
          // SAFETY: literal payload matches ErrorResponse contract for this 401 case.
          res.status(401).json({ error: 'Invalid or expired token' } as ErrorResponse);
          return;
        }
        if (message.includes('Invalid token format')) {
          // SAFETY: literal payload matches ErrorResponse contract for this 401 case.
          res.status(401).json({ error: 'Invalid token format' } as ErrorResponse);
          return;
        }
        if (message.includes('Invalid subject claim') || message.includes('Invalid JTI claim') || message.includes('Invalid token type')) {
          // SAFETY: literal payload matches ErrorResponse contract for this 401 case.
          res.status(401).json({ error: 'Invalid authentication credentials' } as ErrorResponse);
          return;
        }
        // SAFETY: literal payload matches ErrorResponse contract for this 401 case.
        res.status(401).json({ error: 'Invalid or expired token' } as ErrorResponse);
        return;
      }

      // Generic server error. Log only the error class — never the message,
      // which can include connection strings or token material.
      const code = errnoCode(error);
      console.error('Unexpected error in auth/me', error.name, code ?? '');
      // SAFETY: literal payload matches ErrorResponse contract for this 500 case.
      res.status(500).json({ error: 'Internal server error' } as ErrorResponse);
    } else {
      console.error('Unexpected error in auth/me');
      // SAFETY: literal payload matches ErrorResponse contract for this 500 case.
      res.status(500).json({ error: 'Internal server error' } as ErrorResponse);
    }
  }
}