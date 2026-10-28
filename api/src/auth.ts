import { Request, Response } from 'express';
import jwt from 'jsonwebtoken';
import { Pool } from 'pg';
import { isTokenRevoked, getUserWithPasswordCheck } from './authRepository.js';
import { UserResponse } from './authTypes.js';

// Error response interface
interface ErrorResponse {
  error: string;
}

// Database configuration - use the same URL as the Python app
const DATABASE_URL = process.env.DATABASE_URL || '';
const SECRET_KEY = process.env.SECRET_KEY || '';

if (!DATABASE_URL || !SECRET_KEY) {
  throw new Error('DATABASE_URL and SECRET_KEY environment variables must be set');
}

// Create a connection pool (or use global mock for testing)
const pool = (globalThis as any).pool || new Pool({
  connectionString: DATABASE_URL,
  max: 2, // Small pool for serverless functions
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 5000,
});

// Database configuration - use the same URL as the Python app
function verifyToken(token: string): {
  sub: string;
  jti: string;
  type: string;
  exp: number;
  pc?: number;
} {
  try {
    const payload = jwt.verify(token, SECRET_KEY) as any;
    
    // Validate required claims
    if (!payload.sub || typeof payload.sub !== 'string') {
      throw new Error('Invalid subject claim');
    }
    
    if (!payload.jti || typeof payload.jti !== 'string') {
      throw new Error('Invalid JTI claim');
    }
    
    if (payload.type !== 'access') {
      throw new Error('Invalid token type');
    }
    
    return {
      sub: payload.sub,
      jti: payload.jti,
      type: payload.type,
      exp: payload.exp,
      pc: payload.pc
    };
  } catch (error) {
    throw new Error(`Token verification failed: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

/**
 * Main auth/me handler
 */
export default async function authMeHandler(req: Request, res: Response): Promise<void> {
  try {
    // Extract authorization header
    const authHeader = req.headers.authorization;
    
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      res.status(401).json({
        error: 'Missing or invalid authorization header'
      } as ErrorResponse);
      return;
    }
    
    const token = authHeader.substring(7);
    
    // Verify token
    const claims = verifyToken(token);
    
    // Create a database client from the pool
    const client = await pool.connect();
    
    try {
      // Check if token is revoked
      const isRevoked = await isTokenRevoked(client, claims.sub, claims.jti);
      
      if (isRevoked) {
        res.status(401).json({
          error: 'Token has been revoked'
        } as ErrorResponse);
        return;
      }
      
      // Get user with password change check
      const { user, isRevoked: passwordRevoked } = await getUserWithPasswordCheck(
        client, 
        claims.sub, 
        claims.pc
      );
      
      if (passwordRevoked) {
        res.status(401).json({
          error: 'Password changed; please sign in again.'
        } as ErrorResponse);
        return;
      }
      
      // Return user response
      res.json(user);
    } finally {
      // Release the client back to the pool
      client.release();
    }
    
  } catch (error) {
    console.error('Auth/me error:', (error instanceof Error ? error.message : 'Unknown error'));
    
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
      console.error('Unexpected error in auth/me:', error instanceof Error ? error.message : 'Unknown error');
      res.status(500).json({ error: 'Internal server error' } as ErrorResponse);
    } else {
      res.status(500).json({ error: 'Internal server error' } as ErrorResponse);
    }
  }
}