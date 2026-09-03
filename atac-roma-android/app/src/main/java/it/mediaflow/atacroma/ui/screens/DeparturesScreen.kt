package it.mediaflow.atacroma.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import it.mediaflow.atacroma.R
import it.mediaflow.atacroma.data.model.Departure
import it.mediaflow.atacroma.ui.clock
import it.mediaflow.atacroma.ui.etaLabel
import it.mediaflow.atacroma.ui.modeEmoji
import it.mediaflow.atacroma.ui.rememberRepository
import it.mediaflow.atacroma.ui.routeColor
import it.mediaflow.atacroma.ui.vm.DeparturesViewModel
import it.mediaflow.atacroma.ui.vm.VmFactory
import kotlinx.coroutines.delay

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DeparturesScreen(stopId: String, onBack: () -> Unit) {
    val repo = rememberRepository()
    val vm: DeparturesViewModel =
        viewModel(key = "dep_$stopId", factory = VmFactory { DeparturesViewModel(repo, stopId) })

    val stopName by vm.stopName.collectAsStateWithLifecycle()
    val departures by vm.departures.collectAsStateWithLifecycle()
    val loading by vm.loading.collectAsStateWithLifecycle()
    val error by vm.error.collectAsStateWithLifecycle()
    val updatedAt by vm.updatedAt.collectAsStateWithLifecycle()

    // Auto-refresh ogni 30 secondi mentre lo schermo è visibile.
    LaunchedEffect(stopId) {
        while (true) {
            delay(30_000)
            vm.refresh()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(stopName, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        if (updatedAt > 0) {
                            Text(
                                stringResource(R.string.updated_at, clock(updatedAt)),
                                fontSize = 12.sp
                            )
                        }
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = null)
                    }
                },
                actions = {
                    IconButton(onClick = { vm.refresh() }) {
                        Icon(Icons.Filled.Refresh, contentDescription = stringResource(R.string.refresh))
                    }
                }
            )
        }
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            if (loading) LinearProgressIndicator(Modifier.fillMaxWidth())

            when {
                error != null && departures.isEmpty() ->
                    CenteredMessage("${stringResource(R.string.error_generic)}\n$error") { vm.refresh() }

                departures.isEmpty() && !loading ->
                    CenteredMessage(stringResource(R.string.no_departures), null)

                else -> LazyColumn(Modifier.fillMaxSize()) {
                    items(departures) { dep ->
                        DepartureRow(dep)
                        HorizontalDivider()
                    }
                }
            }
        }
    }
}

@Composable
private fun DepartureRow(dep: Departure) {
    val badge = routeColor(dep.routeColor, MaterialTheme.colorScheme.primary)
    Row(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(
            Modifier
                .size(width = 56.dp, height = 40.dp)
                .clip(RoundedCornerShape(8.dp))
                .background(badge),
            contentAlignment = Alignment.Center
        ) {
            Text(
                dep.routeLabel,
                color = Color.White,
                fontWeight = FontWeight.Bold,
                maxLines = 1
            )
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(
                "${modeEmoji(dep.routeType)} ${dep.destination}",
                fontWeight = FontWeight.Medium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            Text(
                etaLabel(dep.etaSeconds),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.primary
            )
        }
        Spacer(Modifier.width(8.dp))
        Column(horizontalAlignment = Alignment.End) {
            val min = dep.etaMinutes
            Text(
                if (min < 1) "•" else "$min",
                fontWeight = FontWeight.Bold,
                fontSize = 20.sp
            )
            Text(stringResource(R.string.min_short), style = MaterialTheme.typography.labelSmall)
        }
    }
}
