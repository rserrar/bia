# Guia d'Arquitectures de Xarxes Neuronals per a Predicció Borsària

## Introducció

Aquest document presenta una guia completa per al disseny d'arquitectures de xarxes neuronals destinades a la predicció de sèries temporals financeres, específicament optimitzades per a:

- **Entrada**: 800 dies de dades borsàries processades com un vector complet
- **Sortides**: Dues prediccions per als següents dies + sortida auxiliar de verificació
- **Framework**: Keras/TensorFlow amb API Funcional

## 1. Arquitectures Base

### 1.1 Deep Neural Networks (DNN)

Les xarxes totalment connectades constitueixen la base més simple per processar els 800 punts d'entrada simultàniament.

**Configuració típica**:
```python
Input(shape=(800,))
Dense(512, activation='relu')
BatchNormalization()
Dropout(0.3)
Dense(256, activation='relu')
BatchNormalization() 
Dropout(0.3)
Dense(128, activation='relu')
Dense(64, activation='relu')
Dense(num_outputs)
```

**Avantatges**: Simplicitat, ràpid d'entrenar, funciona bé com a baseline
**Inconvenients**: No explota l'estructura temporal, propens a overfitting

### 1.2 Convolutional Neural Networks 1D (CNN1D)

Les CNN1D tracten la sèrie temporal com una "imatge" unidimensional, detectant patrons locals i globals.

**Configuració base**:
```python
Reshape((800, 1))
Conv1D(64, kernel_size=5, activation='relu')
Conv1D(128, kernel_size=5, activation='relu')
MaxPooling1D(2)
Conv1D(64, kernel_size=3, activation='relu')
GlobalMaxPooling1D()
Dense(100, activation='relu')
Dense(num_outputs)
```

**Avantatges**: Detecta patrons temporals, parameter sharing, eficient
**Inconvenients**: Pot perdre informació temporal llarga

### 1.3 Architectures Híbrides CNN + Dense

Combinen l'extracció de patrons de CNN amb la capacitat d'integració de les capes denses.

```python
# Extracció de features amb CNN
Conv1D(32, 10, activation='relu')
Conv1D(64, 5, activation='relu') 
GlobalAveragePooling1D()
# Integració amb Dense layers
Dense(200, activation='relu')
Dropout(0.4)
Dense(100, activation='relu')
Dense(num_outputs)
```

## 2. Arquitectures Multi-Branch

### 2.1 Branques per Escales Temporals

Cada branca processa les mateixes dades amb diferents perspectives temporals utilitzant kernels de mides diferents.

**Configuració multi-escala**:
- **Branca 1**: `kernel_size=3` → Patrons diaris
- **Branca 2**: `kernel_size=10` → Patrons setmanals  
- **Branca 3**: `kernel_size=50` → Patrons mensuals
- **Branca 4**: `kernel_size=200` → Tendències trimestrals

### 2.2 Dilated Convolutions

Utilitzen `dilation_rate` per cobrir diferents rangs temporals sense augmentar el nombre de paràmetres exponencialment.

```python
# Diferents receptive fields amb la mateixa mida de kernel
Conv1D(64, kernel_size=3, dilation_rate=1)   # Local
Conv1D(64, kernel_size=3, dilation_rate=4)   # Setmanal
Conv1D(64, kernel_size=3, dilation_rate=20)  # Mensual
Conv1D(64, kernel_size=3, dilation_rate=100) # Trimestral
```

### 2.3 Grouped Convolutions

Divideixen les dades en segments temporals que es processen independentment abans de fusionar-se.

```python
# Divisió temporal
slice_1 = Lambda(lambda x: x[:, :200])(input_layer)
slice_2 = Lambda(lambda x: x[:, 200:400])(input_layer)
slice_3 = Lambda(lambda x: x[:, 400:600])(input_layer)
slice_4 = Lambda(lambda x: x[:, 600:800])(input_layer)
# Processament independent per cada slice
```

## 3. Estratègies de Fusió

### 3.1 Fusió Primerenca vs Tardana

**Fusió Primerenca**: Les branques es combinen aviat i continuen processant juntes
- Permet interacció entre diferents perspectives
- Millor per a patrons complexes interdependents

**Fusió Tardana**: Cada branca desenvolupa la seva representació independentment
- Manté la interpretabilitat de cada perspectiva
- Millor per a ensemble implícit

### 3.2 Attention-Based Fusion

Utilitza mecanismes d'atenció per aprendre automàticament la importància relativa de cada branca.

```python
# Cada branca genera features
attention_weights = Dense(num_branches, activation='softmax')(context)
weighted_branches = Multiply()([branch_outputs, attention_weights])
fused_output = Add()(weighted_branches)
```

### 3.3 Gated Fusion

Empra gates per controlar el flux d'informació de cada branca de manera adaptativa.

```python
gate = Dense(num_branches, activation='sigmoid')(global_context)
gated_branches = Multiply()([branch_outputs, gate])
```

### 3.4 Fusió Jeràrquica

Estructura la fusió en múltiples nivells, primer combinant branques similars i després aquests grups.

```python
# Primer nivell: fusió per tipus
short_term_fused = Concatenate()([branch_1, branch_2])
long_term_fused = Concatenate()([branch_3, branch_4])
# Segon nivell: fusió global
final_fused = Concatenate()([short_term_fused, long_term_fused])
```

## 4. Arquitectures Multi-Output

### 4.1 Shared Backbone + Task-Specific Heads

La majoria del model és compartit, amb especialització només en les capes finals.

```python
# Backbone compartit
shared_repr = backbone_network(inputs)

# Caps específics per cada tasca
prediction_1 = Dense(32, activation='relu', name='pred1')(shared_repr)
prediction_1 = Dense(1, name='day_1_pred')(prediction_1)

prediction_2 = Dense(32, activation='relu', name='pred2')(shared_repr)
prediction_2 = Dense(1, name='day_2_pred')(prediction_2)

# Cap de verificació
reconstruction = Dense(200, name='verification')(shared_repr)
```

### 4.2 Multi-Task Learning amb Loss Weighting

Cada sortida té la seva pròpia loss function amb pesos ajustables.

```python
losses = {
    'day_1_pred': 'mse',
    'day_2_pred': 'mse',
    'verification': 'mse'
}

loss_weights = {
    'day_1_pred': 1.0,
    'day_2_pred': 1.0, 
    'verification': 0.1  # Pes menor per verificació
}
```

## 5. Configuracions Avançades CNN1D

### 5.1 Depthwise Separable Convolutions

`SeparableConv1D` ofereix major eficiència computacional i sovint millor rendiment per sèries temporals.

```python
SeparableConv1D(filters=64, kernel_size=5, activation='relu')
```

### 5.2 Causal Convolutions

`Conv1D(padding='causal')` assegura que només s'utilitza informació del passat, evitant data leakage.

### 5.3 Strided Convolutions

`Conv1D(strides=2)` redueix progressivament la dimensionalitat temporal mentre extreu features.

### 5.4 Residual Connections

Skip connections que permeten entrenar xarxes més profundes i mantenir informació dels nivells baixos.

```python
# Bloc residual típic
x = Conv1D(filters, kernel_size, activation='relu')(input_tensor)
x = Conv1D(filters, kernel_size)(x)
if input_tensor.shape[-1] == filters:
    x = Add()([input_tensor, x])  # Skip connection
x = Activation('relu')(x)
```

## 6. Tècniques de Regularització Específiques

### 6.1 Spatial Dropout

`SpatialDropout1D` en lloc de `Dropout` regular - elimina canals complets en lloc de neurones individuals.

### 6.2 Layer Normalization

`LayerNormalization` sovint supera `BatchNormalization` per sèries temporals llargues.

### 6.3 Gradient Clipping

Essencial amb seqüències de 800 punts per evitar gradient exploding.

```python
optimizer = Adam(clipnorm=1.0)
```

## 7. Arquitectures Experimentals

### 7.1 WaveNet-Style Dilated Blocks

Blocs amb dilatacions exponencials (1, 2, 4, 8, 16...) que cobreixen tot el rang temporal amb poques capes.

### 7.2 Multi-Scale Dense Connections

Cada capa rep inputs de totes les capes anteriors, mantenint informació de diferents resolucions.

### 7.3 Squeeze-and-Excitation Temporal

Mecanisme d'atenció que repondera la importància de diferents canals temporals.

```python
# Global average pooling temporal
gap = GlobalAveragePooling1D()(conv_output)
# Squeeze
squeeze = Dense(channels//reduction_ratio, activation='relu')(gap)
# Excitation  
excitation = Dense(channels, activation='sigmoid')(squeeze)
# Reweighting
excitation = Reshape((1, channels))(excitation)
scaled = Multiply()([conv_output, excitation])
```

## 8. Consideracions d'Implementació

### 8.1 Preprocessing Essencial

- **Normalització/Estandardització**: Z-score o Min-Max scaling
- **Diferenciació**: Per fer la sèrie estacionària si cal
- **Feature Engineering**: Indicadors tècnics (RSI, MACD, mitjanes mòbils)
- **Sliding Windows**: Per augmentar el dataset d'entrenament

### 8.2 Data Augmentation

- **Soroll Gaussià**: Petites pertorbacions a les dades d'entrada
- **Scaling**: Multiplicació per factors aleatoris propers a 1.0
- **Time Warping**: Petites distorsions temporals

### 8.3 Estratègies d'Entrenament

- **Early Stopping**: Monitoritzar validation loss amb paciència adequada
- **Learning Rate Scheduling**: ReduceLROnPlateau o Cosine Annealing
- **Ensemble Methods**: Combinar múltiples models per robustesa

## 9. Arquitectura Recomanada per Començar

### 9.1 Configuració Base

```python
# Multi-branch amb diferents escales + fusió per attention
input_layer = Input(shape=(800, 1))

# Branques amb diferents receptive fields
branch_local = Conv1D(32, 3, activation='relu')(input_layer)
branch_local = GlobalMaxPooling1D()(branch_local)

branch_weekly = Conv1D(32, 10, dilation_rate=2, activation='relu')(input_layer)
branch_weekly = GlobalMaxPooling1D()(branch_weekly)

branch_monthly = Conv1D(32, 50, activation='relu')(input_layer)  
branch_monthly = GlobalMaxPooling1D()(branch_monthly)

# Fusió amb attention
all_branches = Concatenate()([branch_local, branch_weekly, branch_monthly])
attention = Dense(3, activation='softmax')(all_branches)
attended = Multiply()([all_branches, attention])

# Shared backbone
shared = Dense(128, activation='relu')(attended)
shared = Dropout(0.3)(shared)
shared = Dense(64, activation='relu')(shared)

# Multi-output heads
pred_1 = Dense(1, name='prediction_1')(shared)
pred_2 = Dense(1, name='prediction_2')(shared)
verification = Dense(100, name='verification')(shared)
```

### 9.2 Progressió Experimental

1. **Baseline**: CNN1D simple amb GlobalPooling
2. **Multi-branch**: Afegir branques amb diferents kernels
3. **Attention**: Incorporar mecanismes d'atenció
4. **Regularització**: Optimitzar dropout, normalization
5. **Arquitectures avançades**: Residual, WaveNet, etc.

## 10. Mètriques i Validació

### 10.1 Mètriques per Predicció

- **MSE/RMSE**: Error quadràtic mitjà
- **MAE**: Error absolut mitjà
- **MAPE**: Error percentual absolut mitjà
- **Direccional Accuracy**: Percentatge d'encerts en la direcció del moviment

### 10.2 Mètriques per Verificació

- **Reconstruction Loss**: MSE entre entrada original i reconstruïda
- **Correlation**: Correlació entre segments originals i reconstruïts
- **Spectral Analysis**: Comparació de l'espectre de freqüències

### 10.3 Validació Temporal

- **Time Series Split**: Respectar l'ordre temporal en train/validation
- **Walk-Forward Validation**: Validació progressiva simulant condicions reals
- **Purged Cross-Validation**: Evitar data leakage temporal

## 11. Arquitectures Avançades i Combinacions Complexes

### 11.1 Fusions i Ramificacions Complexes

#### Fusió Intermèdia després de Caps Auxiliars

Aquesta tècnica permet supervisió múltiple i integració jeràrquica sofisticada:

```python
# Branques generen sortides auxiliars
aux_output_1 = Dense(32, name='aux_1')(branch_1)
aux_prediction_1 = Dense(1, name='aux_pred_1')(aux_output_1)

aux_output_2 = Dense(32, name='aux_2')(branch_2)  
aux_prediction_2 = Dense(1, name='aux_pred_2')(aux_output_2)

# Re-fusió després dels caps auxiliars
refused = Concatenate()([aux_output_1, aux_output_2, branch_3])
enhanced_repr = Dense(128, activation='relu')(refused)
final_output = Dense(1, name='main_prediction')(enhanced_repr)
```

**Avantatges**:
- Supervisió múltiple millora l'entrenament
- Integració jeràrquica d'informació en diferents nivells
- Cada branca pot especialitzar-se mentre contribueix al resultat final

#### Sortides Jeràrquiques en Cascada

Les sortides s'alimenten seqüencialment en lloc de només en paral·lel:

```python
# Primera predicció
first_pred_features = Dense(64, activation='relu')(shared_backbone)
first_prediction = Dense(1, name='day_1_pred')(first_pred_features)

# Segona predicció utilitza la primera com a context
second_input = Concatenate()([shared_backbone, first_pred_features])
second_pred_features = Dense(64, activation='relu')(second_input)  
second_prediction = Dense(1, name='day_2_pred')(second_pred_features)
```

### 11.2 Arquitectures Mixtes dins del Mateix Model

#### Branques amb Arquitectures Heterogènies

Cada branca utilitza una aproximació arquitectònica diferent:

```python
# Branca CNN per patrons locals
cnn_branch = Conv1D(64, 5, activation='relu')(input_reshaped)
cnn_branch = GlobalMaxPooling1D()(cnn_branch)

# Branca LSTM per context temporal llarg  
lstm_branch = LSTM(64, return_sequences=False)(input_reshaped)

# Branca Dense convencional
dense_branch = Flatten()(input_layer)
dense_branch = Dense(128, activation='relu')(dense_branch)
dense_branch = Dense(64, activation='relu')(dense_branch)

# Fusió de les tres aproximacions
mixed_fusion = Concatenate()([cnn_branch, lstm_branch, dense_branch])
```

#### Processament Selectiu d'Entrada

Diferents branques poden processar segments diferents de les 800 dades:

```python
# Branca 1: últims 200 dies amb alta resolució
recent_data = Lambda(lambda x: x[:, -200:])(input_layer)
recent_branch = Conv1D(32, 3, activation='relu')(recent_data)

# Branca 2: totes les dades amb baixa resolució (downsampling)
downsampled = Lambda(lambda x: x[:, ::4])(input_layer)  # Cada 4t punt
historical_branch = LSTM(32)(downsampled)
```

### 11.3 Atenció Avançada i Rutes Dinàmiques

#### Multi-Head Attention Intern

Self-attention com a component intern del backbone:

```python
class MultiHeadSelfAttention(layers.Layer):
    def __init__(self, d_model, num_heads):
        super().__init__()
        self.num_heads = num_heads
        self.d_model = d_model
        self.depth = d_model // num_heads
        
        self.wq = Dense(d_model)
        self.wk = Dense(d_model)  
        self.wv = Dense(d_model)
        self.dense = Dense(d_model)
        
    def call(self, inputs):
        batch_size = tf.shape(inputs)[0]
        seq_len = tf.shape(inputs)[1]
        
        q = self.wq(inputs)
        k = self.wk(inputs)
        v = self.wv(inputs)
        
        # Reshape per multi-head
        q = tf.reshape(q, (batch_size, seq_len, self.num_heads, self.depth))
        k = tf.reshape(k, (batch_size, seq_len, self.num_heads, self.depth))
        v = tf.reshape(v, (batch_size, seq_len, self.num_heads, self.depth))
        
        # Attention computation
        attention_output = self.scaled_dot_product_attention(q, k, v)
        return self.dense(attention_output)

# Integració en el model
conv_output = Conv1D(128, 5)(input_layer)
attended_output = MultiHeadSelfAttention(128, 8)(conv_output)
```

#### Gating Mechanisms i Rutes Dinàmiques

Gates que controlen dinàmicament el flux d'informació:

```python
# Highway Network style gating
def highway_gate(inputs, gate_activation='sigmoid'):
    gate = Dense(inputs.shape[-1], activation=gate_activation)(inputs)
    transform = Dense(inputs.shape[-1], activation='relu')(inputs)
    carry = Lambda(lambda x: 1.0 - x)(gate)
    
    return Add()([Multiply()([gate, transform]), 
                  Multiply()([carry, inputs])])

# Aplicació en branques
branch_1_gated = highway_gate(branch_1_output)
branch_2_gated = highway_gate(branch_2_output)
```

### 11.4 Residualitat i Densitat de Connexions

#### Deep Skip Connections

Skip connections que salten múltiples capes i fins i tot entre branques:

```python
# Skip connection des de l'entrada fins capes profundes
early_features = Conv1D(32, 3, activation='relu')(input_layer)
deep_features = Conv1D(32, 3, activation='relu')(intermediate_layer)

# Skip connection adaptativa (si les dimensions coincideixen)
if early_features.shape[-1] == deep_features.shape[-1]:
    combined = Add()([early_features, deep_features])
else:
    # Projectió per ajustar dimensions
    projected = Dense(deep_features.shape[-1])(early_features)
    combined = Add()([projected, deep_features])
```

#### Dense Connections Multi-Branca

Cada capa rep inputs de múltiples capes anteriors de diferents branques:

```python
# DenseNet adaptat per multi-branca
layer_1_branch_a = Conv1D(32, 3)(input_a)
layer_1_branch_b = Conv1D(32, 5)(input_b)

# Capa 2 rep inputs de capa 1 i entrada original
layer_2_input = Concatenate()([input_a, input_b, 
                               layer_1_branch_a, layer_1_branch_b])
layer_2_output = Conv1D(64, 3)(layer_2_input)

# Capa 3 rep tots els inputs anteriors
layer_3_input = Concatenate()([input_a, input_b,
                               layer_1_branch_a, layer_1_branch_b,
                               layer_2_output])
```

### 11.5 Modularitat i Composició de Blocs

#### Blocs Modulars Reutilitzables

Definició de components modulars per facilitar experimentació:

```python
def cnn_block(inputs, filters, kernel_size, name_prefix):
    x = Conv1D(filters, kernel_size, activation='relu', 
               name=f'{name_prefix}_conv1')(inputs)
    x = BatchNormalization(name=f'{name_prefix}_bn1')(x)
    x = Conv1D(filters, kernel_size, activation='relu',
               name=f'{name_prefix}_conv2')(x)
    x = BatchNormalization(name=f'{name_prefix}_bn2')(x)
    return x

def attention_block(inputs, d_model, num_heads, name_prefix):
    attention = MultiHeadAttention(num_heads, d_model//num_heads,
                                 name=f'{name_prefix}_mha')(inputs, inputs)
    add_norm1 = LayerNormalization(name=f'{name_prefix}_ln1')(
        Add()([inputs, attention]))
    
    ffn = Dense(d_model*4, activation='relu', 
                name=f'{name_prefix}_ffn1')(add_norm1)
    ffn = Dense(d_model, name=f'{name_prefix}_ffn2')(ffn)
    return LayerNormalization(name=f'{name_prefix}_ln2')(
        Add()([add_norm1, ffn]))

# Composició flexible
tower_1 = cnn_block(input_layer, 64, 5, 'tower1_cnn')
tower_1 = attention_block(tower_1, 64, 8, 'tower1_att')

tower_2 = attention_block(input_layer, 64, 4, 'tower2_att') 
tower_2 = cnn_block(tower_2, 64, 3, 'tower2_cnn')
```

### 11.6 Supervisió Auxiliar Profunda (Deep Supervision)

#### Supervisió a Múltiples Profunditats

Caps auxiliars a diferents nivells de la xarxa:

```python
# Supervisió primerenca (shallow)
shallow_features = cnn_block(input_layer, 32, 5, 'shallow')
shallow_supervision = GlobalAveragePooling1D()(shallow_features)
shallow_pred = Dense(1, name='shallow_prediction')(shallow_supervision)

# Supervisió intermèdia (medium)  
medium_features = cnn_block(shallow_features, 64, 3, 'medium')
medium_supervision = GlobalAveragePooling1D()(medium_features)
medium_pred = Dense(1, name='medium_prediction')(medium_supervision)

# Supervisió profunda (deep) - predicció final
deep_features = attention_block(medium_features, 64, 8, 'deep')
deep_supervision = GlobalAveragePooling1D()(deep_features)
final_pred = Dense(1, name='final_prediction')(deep_supervision)

# Loss combinada amb pesos decreixents per supervisió auxiliar
losses = {
    'shallow_prediction': 'mse',
    'medium_prediction': 'mse', 
    'final_prediction': 'mse'
}
loss_weights = {
    'shallow_prediction': 0.3,
    'medium_prediction': 0.5,
    'final_prediction': 1.0
}
```

### 11.7 Transformers i Auto-atenció Local/Global

#### Transformer Blocks Híbrids

Integració de Transformer components en arquitectures CNN:

```python
def transformer_encoder_block(inputs, d_model, num_heads, dff):
    # Multi-head self-attention
    attn_output = MultiHeadAttention(num_heads, d_model//num_heads)(inputs, inputs)
    attn_output = Dropout(0.1)(attn_output)
    out1 = LayerNormalization()(Add()([inputs, attn_output]))
    
    # Feed forward network
    ffn_output = Dense(dff, activation='relu')(out1)
    ffn_output = Dense(d_model)(ffn_output)
    ffn_output = Dropout(0.1)(ffn_output)
    
    return LayerNormalization()(Add()([out1, ffn_output]))

# Híbrid CNN + Transformer
conv_features = Conv1D(128, 5, activation='relu')(input_layer)
transformer_features = transformer_encoder_block(conv_features, 128, 8, 512)
hybrid_output = GlobalAveragePooling1D()(transformer_features)
```

#### Atenció Local vs Global

Combinació d'atenció en finestres locals i global:

```python
def local_attention(inputs, window_size=50):
    # Divideix en finestres locals
    batch_size = tf.shape(inputs)[0]
    seq_len = tf.shape(inputs)[1]
    
    # Reshape per finestres locals
    windowed = tf.reshape(inputs, (batch_size, -1, window_size, inputs.shape[-1]))
    
    # Atenció dins cada finestra
    local_attn = MultiHeadAttention(4, 32)(windowed, windowed)
    
    # Reshape de tornada
    return tf.reshape(local_attn, (batch_size, seq_len, inputs.shape[-1]))

def global_attention(inputs):
    # Atenció sobre tota la seqüència
    return MultiHeadAttention(8, 64)(inputs, inputs)

# Combinació local + global
local_attended = local_attention(conv_output, window_size=40)
global_attended = global_attention(conv_output)
combined_attention = Add()([local_attended, global_attended])
```

### 11.8 Esquema Arquitectònic Complet

#### Implementació del Patró Complet

```python
def build_advanced_architecture(input_shape=(800, 1)):
    inputs = Input(shape=input_shape)
    
    # === BACKBONE MULTI-BRANCA ===
    # Branca CNN
    cnn_branch = cnn_block(inputs, 64, 5, 'cnn')
    cnn_aux = Dense(1, name='cnn_aux_pred')(GlobalMaxPooling1D()(cnn_branch))
    
    # Branca Transformer  
    transformer_branch = transformer_encoder_block(inputs, 64, 4, 256)
    trans_aux = Dense(1, name='trans_aux_pred')(GlobalAveragePooling1D()(transformer_branch))
    
    # Branca Mixed (local + global attention)
    mixed_branch = local_attention(inputs, 40)
    mixed_branch = global_attention(mixed_branch)
    mixed_aux = Dense(1, name='mixed_aux_pred')(GlobalAveragePooling1D()(mixed_branch))
    
    # === FUSIÓ INTERMÈDIA ===
    # Extreu features dels caps auxiliars
    cnn_features = Dense(32, activation='relu')(GlobalMaxPooling1D()(cnn_branch))
    trans_features = Dense(32, activation='relu')(GlobalAveragePooling1D()(transformer_branch))  
    mixed_features = Dense(32, activation='relu')(GlobalAveragePooling1D()(mixed_branch))
    
    # Re-fusió amb atenció
    all_features = tf.stack([cnn_features, trans_features, mixed_features], axis=1)
    fusion_attention = MultiHeadAttention(4, 16)(all_features, all_features)
    fused_features = GlobalAveragePooling1D()(fusion_attention)
    
    # === CAPS FINALS ===
    # Deep supervision final
    enhanced_repr = Dense(128, activation='relu')(fused_features)
    enhanced_repr = Dense(64, activation='relu')(enhanced_repr)
    
    # Sortides principals jeràrquiques
    pred_1_features = Dense(32, activation='relu')(enhanced_repr)
    prediction_1 = Dense(1, name='prediction_1')(pred_1_features)
    
    # Segona predicció usa la primera com a context
    pred_2_input = Concatenate()([enhanced_repr, pred_1_features])
    pred_2_features = Dense(32, activation='relu')(pred_2_input)
    prediction_2 = Dense(1, name='prediction_2')(pred_2_features)
    
    # Verificació (reconstrucció parcial)
    verification = Dense(100, name='verification')(enhanced_repr)
    
    return Model(inputs=inputs, 
                outputs=[prediction_1, prediction_2, verification,
                        cnn_aux, trans_aux, mixed_aux])
```

#### Configuració de Loss Complexa

```python
losses = {
    'prediction_1': 'mse',
    'prediction_2': 'mse',
    'verification': 'mse',
    'cnn_aux_pred': 'mse',
    'trans_aux_pred': 'mse', 
    'mixed_aux_pred': 'mse'
}

loss_weights = {
    'prediction_1': 1.0,        # Màxim pes
    'prediction_2': 1.0,        # Màxim pes
    'verification': 0.2,        # Supervisió auxiliar
    'cnn_aux_pred': 0.3,        # Supervisió intermèdia
    'trans_aux_pred': 0.3,      # Supervisió intermèdia
    'mixed_aux_pred': 0.3       # Supervisió intermèdia
}
```

## Conclusions

L'èxit en la predicció borsària amb xarxes neuronals requereix una aproximació sistemàtica que combini arquitectures apropiades, regularització adequada i validació rigorosa. La modularitat de les arquitectures presentades permet experimentació eficient i adaptació a les característiques específiques de cada dataset financer.

Les arquitectures avançades ofereixen flexibilitat extrema per capturar patrons complexes a través de múltiples nivells de representació, fusió intel·ligent d'informació i supervisió profunda. La clau està en començar amb configuracions simples i afegir complexitat gradualment, sempre validant que cada component afegeix valor real al model.