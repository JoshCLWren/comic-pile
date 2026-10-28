import type { Request, Response } from 'express';
import { getAuthenticatedUser } from './authService.js';

interface ErrorResponse {
  error: string;
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
        res.status(401).json({ error: 'Missing or invalid authorization header' } as ErrorResponse);
        return;
      }
      if (message === 'Token has been revoked' || message.includes('Token has been revoked')) {
        res.status(401).json({ error: 'Token has been revoked' } as ErrorResponse);
        return;
      }
      if (message === 'User not found' || message.includes('User not found')) {
        res.status(401).json({ error: 'User not found' } as ErrorResponse);
        return;
      }
      if (message === 'Password changed; please sign in again.' || message.includes('Password changed')) {
        res.status(401).json({ error: 'Password changed; please sign in again.' } as ErrorResponse);
        return;
      }
      if (message.startsWith('Token verification failed:')) {
        if (message.includes('jwt expired') || message.includes('Invalid or expired token')) {
          res.status(401).json({ error: 'Invalid or expired token' } as ErrorResponse);
          return;
        }
        if (message.includes('Invalid token format')) {
          res.status(401).json({ error: 'Invalid token format' } as ErrorResponse);
          return;
        }
        if (message.includes('Invalid subject claim') || message.includes('Invalid JTI claim') || message.includes('Invalid token type')) {
          res.status(401).json({ error: 'Invalid authentication credentials' } as ErrorResponse);
          return;
        }
        res.status(401).json({ error: 'Invalid or expired token' } as ErrorResponse);
        return;
      }

      // Generic server error
      console.error('Unexpected error in auth/me');
      res.status(500).json({ error: 'Internal server error' } as ErrorResponse);
    } else {
      res.status(500).json({ error: 'Internal server error' } as ErrorResponse);
    }
  }
}