package it.mediaflow.atacroma.ui

import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext
import it.mediaflow.atacroma.AtacApp
import it.mediaflow.atacroma.data.repo.TransitRepository

@Composable
fun rememberRepository(): TransitRepository {
    val ctx = LocalContext.current
    return (ctx.applicationContext as AtacApp).repository
}
