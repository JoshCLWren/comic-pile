import { createServer } from 'http';
import express from 'express';
import authMeHandler from '../auth';

// Create an express app for Vercel serverless functions
const app = express();
app.use(express.json());

// Set CORS headers for API requests
app.use((req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  next();
});

// Handle preflight requests
app.options('*', (req, res) => {
  res.writeHead(200);
  res.end();
});

// Only handle GET requests for auth/me
app.get('*', async (req, res) => {
  // Only handle auth/me endpoint
  if (req.path !== '/api/v1/auth/me') {
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Not found' }));
    return;
  }
  
  // Handle the request with our auth/me handler
  await authMeHandler(req, res);
});

// Create a server from the express app
const server = createServer(app);

// Export the server for Vercel
export default server;