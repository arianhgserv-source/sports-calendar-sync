const UPSTREAM_URL =
  'https://raw.githubusercontent.com/arianhgserv-source/sports-calendar-sync/main/calendar.ics';

export default {
  async fetch(request, env, ctx) {
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('Not Found', { status: 404 });
    }

    const url = new URL(request.url);
    if (url.pathname !== '/' && url.pathname !== '/calendar.ics') {
      return new Response('Not Found', { status: 404 });
    }

    try {
      const response = await fetch(UPSTREAM_URL, {
        method: request.method,
      });

      if (!response.ok) {
        return new Response('Bad Gateway', { status: 502 });
      }

      const headers = new Headers();
      headers.set('Content-Type', 'text/calendar; charset=utf-8');
      headers.set('Cache-Control', 'public, max-age=3600');
      headers.set('Content-Disposition', 'inline; filename=calendar.ics');

      return new Response(request.method === 'HEAD' ? null : response.body, {
        status: 200,
        headers,
      });
    } catch {
      return new Response('Bad Gateway', { status: 502 });
    }
  },
};
