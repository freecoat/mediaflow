package it.mediaflow.atacroma.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import it.mediaflow.atacroma.R
import it.mediaflow.atacroma.data.model.ServiceAlert
import it.mediaflow.atacroma.ui.dateTime
import it.mediaflow.atacroma.ui.rememberRepository
import it.mediaflow.atacroma.ui.vm.AlertsViewModel
import it.mediaflow.atacroma.ui.vm.VmFactory

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AlertsScreen() {
    val repo = rememberRepository()
    val vm: AlertsViewModel = viewModel(factory = VmFactory { AlertsViewModel(repo) })

    val alerts by vm.alerts.collectAsStateWithLifecycle()
    val loading by vm.loading.collectAsStateWithLifecycle()
    val error by vm.error.collectAsStateWithLifecycle()

    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text(stringResource(R.string.tab_alerts)) },
            actions = {
                IconButton(onClick = { vm.refresh() }) {
                    Icon(Icons.Filled.Refresh, contentDescription = stringResource(R.string.refresh))
                }
            }
        )
        if (loading) LinearProgressIndicator(Modifier.fillMaxWidth())

        when {
            error != null && alerts.isEmpty() ->
                CenteredMessage("${stringResource(R.string.error_generic)}\n$error") { vm.refresh() }

            alerts.isEmpty() && !loading ->
                CenteredMessage(stringResource(R.string.no_alerts), null)

            else -> LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                items(alerts, key = { it.id }) { AlertCard(it) }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AlertCard(alert: ServiceAlert) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp)) {
            Text(alert.title, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleMedium)
            if (alert.description.isNotBlank()) {
                Spacer(Modifier.size(6.dp))
                Text(alert.description, style = MaterialTheme.typography.bodyMedium)
            }
            if (alert.routes.isNotEmpty()) {
                Spacer(Modifier.size(8.dp))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    alert.routes.take(20).forEach { r ->
                        AssistChip(
                            onClick = {},
                            label = { Text(r) },
                            colors = AssistChipDefaults.assistChipColors()
                        )
                    }
                }
            }
            val period = periodLabel(alert)
            if (period != null) {
                Spacer(Modifier.size(8.dp))
                Text(period, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.secondary)
            }
        }
    }
}

private fun periodLabel(a: ServiceAlert): String? {
    val from = a.activeFromEpoch
    val to = a.activeToEpoch
    return when {
        from != null && to != null -> "Dal ${dateTime(from)} al ${dateTime(to)}"
        from != null -> "Dal ${dateTime(from)}"
        to != null -> "Fino al ${dateTime(to)}"
        else -> null
    }
}
