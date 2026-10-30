#!/usr/bin/env python3
"""Патч для Droidbubble: остров РАСТЯГИВАЕТСЯ из камеры вместо "открытия" карточки.
Запускается в GitHub Actions перед сборкой. Если якорь не найден - падает с понятной ошибкой.
"""
import glob
import re
import sys


def fail(msg):
    # ::error:: показывает текст прямо на странице сборки (в Annotations)
    print('::error::' + msg.replace('\n', ' | '))
    sys.exit(1)


def find_file():
    if len(sys.argv) > 1:
        return sys.argv[1]
    for p in glob.glob('app/src/**/*.kt', recursive=True):
        with open(p, encoding='utf-8') as f:
            if 'fun IslandOverlayRoot(' in f.read():
                return p
    names = [p for p in glob.glob('app/src/**/*.kt', recursive=True) if 'sland' in p]
    fail('Файл с IslandOverlayRoot не найден. Похожие файлы: ' + ', '.join(names[:12]))


PATCHES = [
    # 1. Настройки-константы (меняй как хочешь)
    (
        'import kotlin.math.sin',
        '''import kotlin.math.sin

// ===== НАСТРОЙКИ РАСТЯГИВАНИЯ (меняй как хочешь) =====
private const val ISLAND_STRETCH = true            // true = остров растягивается, false = как было
private const val ISLAND_ANCHOR_TOP = true         // true = остров прижат к камере и тянется вниз
private val ISLAND_ANCHOR_EXTRA = 52.dp            // на сколько тянется вниз под камеру
private const val ISLAND_COLLAPSE_STIFFNESS = 520f // скорость сворачивания (больше = быстрее)
private const val ISLAND_SWIPE_DOWN_EXPAND = true  // свайп вниз по острову раскрывает его''',
    ),
    # 2. Флаги режима
    (
        'val speedSq = speed * speed',
        '''val speedSq = speed * speed

    // Режим растягивания работает для обычной точки-камеры (по центру)
    val stretch = ISLAND_STRETCH && !settings.isLeftCutout && !settings.isTeardropCutout
    val anchored = stretch && ISLAND_ANCHOR_TOP
    val anchorExtra = if (anchored) ISLAND_ANCHOR_EXTRA else 0.dp''',
    ),
    # 3-4. Плавное сворачивание пружиной (без рывков) вместо tween
    (
        'else -> tween<androidx.compose.ui.unit.Dp>(',
        'else -> if (stretch) spring<androidx.compose.ui.unit.Dp>(dampingRatio = 1f, stiffness = ISLAND_COLLAPSE_STIFFNESS * speedSq) else tween<androidx.compose.ui.unit.Dp>(',
    ),
    (
        'else -> tween<Float>(',
        'else -> if (stretch) spring<Float>(dampingRatio = 1f, stiffness = ISLAND_COLLAPSE_STIFFNESS * speedSq) else tween<Float>(',
    ),
    # 5. Стартовая ширина карточки = ширина таблетки (растягиваемся из неё)
    (
        'val screenWidth = configuration.screenWidthDp.dp',
        '''val screenWidth = configuration.screenWidthDp.dp
    val morphStartWidth = if (isDual) compactMainFull
        else if (isOccupied || hasPersistent) settings.widthDp.dp.coerceAtLeast(124.dp)
        else settings.widthDp.dp''',
    ),
    (
        '(340.dp * settings.expandedScale).coerceAtMost(screenWidth - 16.dp) } else { 0.dp }',
        '''(340.dp * settings.expandedScale).coerceAtMost(screenWidth - 16.dp)
    } else {
        if (stretch) morphStartWidth else 0.dp
    }''',
    ),
    # 6. Верх остаётся у камеры, остров тянется вниз
    (
        '(settings.topOffsetDp + 52).dp',
        '(settings.topOffsetDp + (if (anchored) 0 else 52)).dp',
    ),
    # 7. Высота: плюс запас под камеру
    (
        'animateDpAsState(targetValue = targetCard1Height,',
        'animateDpAsState(targetValue = if (isExpanded && anchored) targetCard1Height + anchorExtra else targetCard1Height,',
    ),
    # 8. Контент карточки сдвигается вниз, чтобы не лезть на камеру
    (
        '.fillMaxSize() .padding( horizontal = ((if (primaryPriority == IslandPriority.FLASHLIGHT)',
        '.fillMaxSize() .padding(top = anchorExtra) .padding( horizontal = ((if (primaryPriority == IslandPriority.FLASHLIGHT)',
    ),
    # 9. Не растворять карточку при сворачивании - она сжимается обратно в таблетку
    (
        'val cardContainerAlpha = if (isExpanded) 1f else',
        'val cardContainerAlpha = if (isExpanded || stretch) 1f else',
    ),
    # 10. Свайп вниз по таблетке раскрывает остров
    (
        '.combinedClickable( interactionSource = remember { MutableInteractionSource() }, indication = null, onClick = { if (!isExpanded && (isOccupied || hasPersistent) && !isUnlock',
        '''.then(
                            if (ISLAND_SWIPE_DOWN_EXPAND) Modifier.pointerInput(
                                isExpanded, isOccupied, hasPersistent, isUnlock, isBluetooth, isRingerMode, primaryPriority
                            ) {
                                var acc = 0f
                                detectVerticalDragGestures(
                                    onDragStart = { acc = 0f },
                                    onDragEnd = { acc = 0f },
                                    onDragCancel = { acc = 0f }
                                ) { _, dragAmount ->
                                    acc += dragAmount
                                    if (acc > 18f && !isExpanded && (isOccupied || hasPersistent) && !isUnlock && !isBluetooth && !isRingerMode) {
                                        acc = -100000f
                                        triggerHaptic()
                                        IslandStateManager.expand(primaryPriority)
                                    }
                                }
                            } else Modifier
                        )
                        .combinedClickable( interactionSource = remember { MutableInteractionSource() }, indication = null, onClick = { if (!isExpanded && (isOccupied || hasPersistent) && !isUnlock''',
    ),
]


def main():
    path = find_file()
    with open(path, encoding='utf-8') as f:
        s = f.read()
    if 'ISLAND_STRETCH' in s:
        print('Уже пропатчено, пропускаю')
        return
    for i, (old, new) in enumerate(PATCHES, 1):
        pat = r'\s+'.join(re.escape(t) for t in old.split())
        found = len(re.findall(pat, s))
        if found != 1:
            fail(f'ОШИБКА патча №{i} в {path}: якорь найден {found} раз(а): {old[:80]}')
        s = re.sub(pat, lambda m: new, s, count=1)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(s)
    print(f'Готово: пропатчен {path} ({len(PATCHES)} правок)')


main()
