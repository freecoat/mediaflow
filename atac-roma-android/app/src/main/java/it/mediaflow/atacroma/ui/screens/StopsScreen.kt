package it.mediaflow.atacroma.ui.screens

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MyLocation
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.google.android.gms.location.LocationServices
import it.mediaflow.atacroma.R
import it.mediaflow.atacroma.data.local.StopEntity
import it.mediaflow.atacroma.ui.rememberRepository
import it.mediaflow.atacroma.ui.vm.StaticState
import it.mediaflow.atacroma.ui.vm.StopsViewModel
import it.mediaflow.atacroma.ui.vm.VmFactory

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StopsScreen(onStopClick: (String) -> Unit) {
    val repo = rememberRepository()
    val vm: StopsViewModel = viewModel(factory = VmFactory { StopsViewModel(repo) })

    val staticState by vm.static.collectAsStateWithLifecycle()
    val query by vm.query.collectAsStateWithLifecycle()
    val results by vm.results.collectAsStateWithLifecycle()
    val nearby by vm.nearby.collectAsStateWithLifecycle()

    val context = LocalContext.current

    fun fetchNearby() {
        @SuppressLint("MissingPermission")
        val client = LocationServices.getFusedLocationProviderClient(context)
        client.lastLocation.addOnSuccessListener { loc ->
            if (loc != null) vm.loadNearby(loc.latitude, loc.longitude)
        }
    }

    val permLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted -> if (granted) fetchNearby() }

    fun onNearbyClick() {
        val granted = ContextCompat.checkSelfPermission(
            context, Manifest.permission.ACCESS_FINE_LOCATION
        ) == PackageManager.PERMISSION_GRANTED
        if (granted) fetchNearby() else permLauncher.launch(Manifest.permission.ACCESS_FINE_LOCATION)
    }

    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text(stringResource(R.string.app_name)) },
            actions = {
                IconButton(onClick = { vm.refreshStatic() }) {
                    Icon(Icons.Filled.Refresh, contentDescription = stringResource(R.string.update_static))
                }
            }
        )

        when (val s = staticState) {
            is StaticState.Loading -> CenteredLoader(stringResource(R.string.loading_static))
            is StaticState.Error -> CenteredMessage("${stringResource(R.string.error_generic)}\n${s.message}") {
                vm.ensureStatic()
            }
            is StaticState.Ready -> {
                OutlinedTextField(
                    value = query,
                    onValueChange = vm::onQueryChange,
                    singleLine = true,
                    leadingIcon = { Icon(Icons.Filled.Search, null) },
                    placeholder = { Text(stringResource(R.string.search_hint)) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 8.dp)
                )
                FilledTonalButton(
                    onClick = { onNearbyClick() },
                    modifier = Modifier.padding(horizontal = 12.dp)
                ) {
                    Icon(Icons.Filled.MyLocation, null)
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.nearby))
                }

                val list = if (query.isBlank()) nearby else results
                if (list.isEmpty() && query.isNotBlank()) {
                    CenteredMessage(stringResource(R.string.no_stops), null)
                } else {
                    LazyColumn(Modifier.fillMaxSize()) {
                        items(list, key = { it.stopId }) { stop ->
                            StopRow(stop) { onStopClick(stop.stopId) }
                            HorizontalDivider()
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun StopRow(stop: StopEntity, onClick: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(Modifier.fillMaxWidth()) {
            Text(stop.name, fontWeight = FontWeight.SemiBold)
            if (!stop.code.isNullOrBlank()) {
                Text("Palina ${stop.code}", style = androidx.compose.material3.MaterialTheme.typography.bodySmall)
            }
        }
    }
}

@Composable
fun CenteredLoader(message: String) {
    Column(
        Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        CircularProgressIndicator()
        Spacer(Modifier.size(16.dp))
        Text(message)
    }
}

@Composable
fun CenteredMessage(message: String, onRetry: (() -> Unit)?) {
    Column(
        Modifier
            .fillMaxSize()
            .padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(message)
        if (onRetry != null) {
            Spacer(Modifier.size(12.dp))
            FilledTonalButton(onClick = onRetry) { Text(stringResource(R.string.refresh)) }
        }
    }
}
