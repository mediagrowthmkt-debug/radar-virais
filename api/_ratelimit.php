<?php
/**
 * Rate limit por IP, baseado em arquivo (sem Redis). Checklist #23 (Parte 4).
 * Freia flood/abuso de escrita sem atrapalhar uso legitimo. FAIL-OPEN.
 * Incluido no topo do api.php (logo apos o handler de OPTIONS).
 */
(function () {
  try {
    $ip = $_SERVER['REMOTE_ADDR'] ?? 'x';
    $isWrite = ((($_SERVER['REQUEST_METHOD'] ?? 'GET')) === 'POST');
    $limit  = $isWrite ? 30 : 200;   // requisicoes por janela
    $window = 60;                     // segundos
    $dir = sys_get_temp_dir() . '/mg_rl';
    if (!is_dir($dir)) { @mkdir($dir, 0700, true); }
    $key = $dir . '/' . md5($ip . '|' . ($isWrite ? 'w' : 'r'));
    $now = time();
    $st = @json_decode(@file_get_contents($key), true);
    if (!is_array($st) || ($now - ($st['t'] ?? 0)) > $window) { $st = ['t' => $now, 'c' => 0]; }
    $st['c']++;
    @file_put_contents($key, json_encode($st), LOCK_EX);
    if ($st['c'] > $limit) {
      http_response_code(429);
      header('Retry-After: ' . $window);
      header('Content-Type: application/json; charset=utf-8');
      echo json_encode(['erro' => 'rate limit excedido']);
      exit;
    }
  } catch (\Throwable $e) { /* fail-open: nunca derruba a API por causa do limitador */ }
})();
