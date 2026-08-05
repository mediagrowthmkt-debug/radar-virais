<?php
/**
 * Backend do RADAR DE VIRAIS — MediaGrowth (Hostinger).
 * Estado por SLUG num JSON (data/<slug>.json), com trava de arquivo.
 * As DECISOES sao chaveadas pelo ID ESTAVEL do item (sha1 do coletor) — por isso a
 * aprovacao sobrevive a recoleta de hora em hora: o seed troca, as decisoes ficam.
 *
 * Endpoints:
 *   GET  api.php?action=get&slug=<slug>                         -> estado atual
 *   POST api.php  action=decide   slug id status note by        -> aprova/descarta/limpa 1 item
 *   POST api.php  action=reviewer slug by                       -> grava quem esta avaliando
 *
 * status: approved | rejected | pending. 'approved' exige 'by' (nome de quem aprovou).
 * Sem login (pagina publica por slug). CORS liberado (roda no GitHub Pages).
 */
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');
header('Content-Type: application/json; charset=utf-8');
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }

$DATA = __DIR__ . '/data';
if (!is_dir($DATA)) { @mkdir($DATA, 0775, true); }

function bad($msg) { http_response_code(400); echo json_encode(['erro' => $msg]); exit; }
function slug_ok($s) { return is_string($s) && preg_match('/^[a-z0-9\-]{1,64}$/', $s); }
function clip($s, $n) { $s = is_string($s) ? $s : ''; return mb_substr(trim($s), 0, $n); }

$slug = $_REQUEST['slug'] ?? '';
if (!slug_ok($slug)) bad('slug invalido');
$file = "$DATA/$slug.json";

function fresh() { return ['decisions' => new stdClass(), 'reviewer' => '']; }

function load_state($file) {
  if (!file_exists($file)) return fresh();
  $j = json_decode(file_get_contents($file), true);
  if (!is_array($j)) return fresh();
  if (!isset($j['decisions'])) $j['decisions'] = new stdClass();
  if (!isset($j['reviewer']))  $j['reviewer']  = '';
  return $j;
}

$action = $_REQUEST['action'] ?? 'get';

if ($action === 'get') {
  echo json_encode(load_state($file), JSON_UNESCAPED_UNICODE);
  exit;
}

/* ---- escrita: trava exclusiva ---- */
$fp = fopen($file, 'c+');
if (!$fp) bad('io');
flock($fp, LOCK_EX);
$st = json_decode(stream_get_contents($fp), true);
if (!is_array($st)) $st = ['decisions' => [], 'reviewer' => ''];
if (!isset($st['decisions']) || !is_array($st['decisions'])) $st['decisions'] = [];
if (!isset($st['reviewer'])) $st['reviewer'] = '';

function commit($fp, $st) {
  ftruncate($fp, 0); rewind($fp);
  fwrite($fp, json_encode($st, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));
  fflush($fp);
  flock($fp, LOCK_UN); fclose($fp);
  echo json_encode($st, JSON_UNESCAPED_UNICODE);
  exit;
}
function abort_lock($fp, $msg) { flock($fp, LOCK_UN); fclose($fp); bad($msg); }

if ($action === 'decide') {
  $id     = clip($_POST['id'] ?? '', 40);
  $status = clip($_POST['status'] ?? '', 12);
  $note   = clip($_POST['note'] ?? '', 1500);
  $by     = clip($_POST['by'] ?? '', 80);
  if ($id === '') abort_lock($fp, 'id vazio');
  if (!in_array($status, ['approved', 'rejected', 'pending'], true)) abort_lock($fp, 'status invalido');
  if ($status === 'approved' && $by === '') abort_lock($fp, 'nome obrigatorio pra aprovar');
  if ($by !== '') $st['reviewer'] = $by;

  if ($status === 'pending' && $note === '') {
    unset($st['decisions'][$id]);
  } else {
    $st['decisions'][$id] = ['status' => $status, 'note' => $note, 'by' => $by, 'at' => date('c')];
  }
  commit($fp, $st);
}

if ($action === 'reviewer') {
  $by = clip($_POST['by'] ?? '', 80);
  $st['reviewer'] = $by;
  commit($fp, $st);
}

abort_lock($fp, 'action invalida');
