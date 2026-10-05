// сумма элементов массива (русский комментарий тоже отбрасывается)
function sum(a, n) returns s:int
{
    assume(length(a) == n);
    s = 0;
    i = 0;
    while (i < n) invariant (i <= n)
    {
        s = s + a[i];   // накапливаем сумму
        i = i + 1;
    }
    assert(s >= 0);
    x = 01;             // ошибка: число с ведущим нулём
}
